"""Run with python -m mcp_adapter.server; Streamable HTTP at localhost:8000/mcp."""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from .backend_client import BackendClient, BackendError
from .schemas import AdapterResponse, SellOrdersInput, HistoryInput, ProductionInput

PRODUCTION_CONTEXT = (
    "Production quotes use the backend's cached minimum sell percentile across four regions, "
    "not a selected production market. These are material costs, not net profit after fees or hauling."
)


def create_server(backend=None):
    backend = backend or BackendClient()
    server = MCPServer(
        "eve-industry", version="0.1.0",
        instructions="Report incomplete costs and missing_prices before recommendations. Never interpret null costs as zero or incomplete plans as complete shopping lists. Use exact EVE names, preserving numbers. Production modifiers default to zero; report the returned inputs. Backend errors are failures, not empty results.",
    )
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                  idempotent_hint=True, open_world_hint=True)

    async def invoke(path, params, production=False):
        try:
            data = await backend.get(path, params)
        except BackendError as exc:
            raise ToolError(str(exc)) from exc
        warnings = []
        if production:
            warnings.append(PRODUCTION_CONTEXT)
            if data.get("cost_complete") is False:
                warnings.append("Cost is incomplete. Inspect missing_prices and incomplete_reasons; do not claim building is cheaper.")
            elif data.get("cost_complete") is not True:
                warnings.append("Backend did not report cost completeness; it cannot be assumed complete.")
            if params.get("fit"):
                warnings.append("Backend adds fit costs to the total, but its comparison quote covers only the primary item.")
        return AdapterResponse(data=data, warnings=warnings)

    @server.tool(title="Get sell orders", annotations=annotations)
    async def get_sell_orders(request: SellOrdersInput) -> AdapterResponse:
        """Get public regional sell orders, cheapest first. Supply name or type_id. system_name filters a solar system, not a station. top is capped at 100."""
        params = request.model_dump(exclude_none=True)
        if "type_id" in params:
            params["typeId"] = params.pop("type_id")
        if "system_name" in params:
            params["scan"] = params.pop("system_name")
        params["cheapest"] = str(params["cheapest"]).lower()
        params["mode"] = "market"
        return await invoke("/api/main", params)

    @server.tool(title="Get regional market history", annotations=annotations)
    async def get_market_history(request: HistoryInput) -> AdapterResponse:
        """Get daily regional market history and summary. days limits latest available records; omit for all available history. This is regional volume, not station liquidity."""
        return await invoke("/market-history", request.model_dump(exclude_none=True))

    @server.tool(title="Get production tree", annotations=annotations)
    async def get_production_tree(request: ProductionInput) -> AdapterResponse:
        """Get a recursive manufacturing or reaction tree with quantities, costs and completeness. Modifiers default to zero and are echoed by the backend."""
        return await invoke("/api/main", {**request.model_dump(), "mode": "tree"}, True)

    @server.tool(title="Get material requirements", annotations=annotations)
    async def get_material_requirements(request: ProductionInput) -> AdapterResponse:
        """Get flattened raw materials and hybrid build/buy requirements for manufacturing or reactions. Incomplete plans are not complete shopping lists."""
        return await invoke("/api/main", {**request.model_dump(), "mode": "raw"}, True)

    @server.tool(title="Analyze build versus buy", annotations=annotations)
    async def analyze_build_vs_buy(request: ProductionInput) -> AdapterResponse:
        """Get existing backend build/buy comparisons, recursive evidence and plans. Incomplete costs cannot support a building-is-cheaper conclusion. Does not scan candidates or calculate net profit."""
        return await invoke("/api/main", {**request.model_dump(), "mode": "tree"}, True)

    return server


if __name__ == "__main__":
    create_server().run(transport="streamable-http", host="127.0.0.1", port=8000,
                        stateless_http=True, json_response=True)

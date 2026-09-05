# Stage 2: EVE Industry MCP adapter

This independent, read-only adapter calls `https://eve-market-weld.vercel.app`.
It does not import the backend, open SQLite, recalculate costs, or change the GPT.
The implementation follows [OpenAI's current MCP server guidance](https://developers.openai.com/plugins/build/mcp-server)
and the [official Python SDK v2 guidance](https://py.sdk.modelcontextprotocol.io/migration/).
No plugin manifests, skills, authentication or deployment configuration are included.

## Run locally

Python 3.11 or newer:

```sh
python -m pip install -r mcp_adapter/requirements.txt
python -m mcp_adapter.server
```

Streamable HTTP endpoint: `http://127.0.0.1:8000/mcp`. The official SDK runs
stateless HTTP with JSON responses and loopback host/origin protections. This
is a local server only; no public MCP endpoint has been deployed or installed.
`mcp==2.1.1` supplies MCPServer, protocol types and Uvicorn; the adapter explicitly
pins `httpx==0.28.1` and `pydantic==2.13.5`. The SDK additionally uses its own
`httpx2` dependency; the backend client deliberately uses the independent HTTPX
client named in its requirements.

## Exact tools and inputs

The complete generated discovery document, including input/output JSON Schemas
and annotations, is [tool-schemas.json](tool-schemas.json). Every tool accepts
one required object named `request`. Extra fields inside request are rejected.
Names/locations are strings of 1–256 characters containing a non-whitespace
character; spelling and numbers are preserved, not singularised or rewritten.

| Tool | Fields inside request | Backend mapping |
| --- | --- | --- |
| `get_sell_orders` | `name?: string/null`, `type_id?: positive integer/null` (at least one nonnull required); `region_name?: string/null`, `system_name?: string/null`, `cheapest: boolean=false`, `top: integer=10` (1–100) | GET `/api/main`, fixed market mode; type_id → typeId, system_name → scan, cheapest → lowercase string |
| `get_market_history` | Required `name: string`, `region_name: string`; `days?: positive integer/null` | GET `/market-history`, never the internal routing query |
| `get_production_tree` | Production fields below | GET `/api/main`, fixed tree mode |
| `get_material_requirements` | Production fields below | GET `/api/main`, fixed raw mode |
| `analyze_build_vs_buy` | Production fields below | GET `/api/main`, fixed tree mode to retain recursive comparison evidence |

Production fields: required `name: string`; optional `quantity: positive integer=1`,
`fit: string=""` (maximum 8000 characters), and these twelve integer fields,
each defaulting to zero with the same unrestricted ranges as the backend:

- `blueprint_me`
- `production_efficiency`
- `blueprint_te`
- `industry_skill`
- `advanced_industry_skill`
- `mass_production_skill`
- `advanced_mass_production_skill`
- `supply_chain_management_skill`
- `structure_material_bonus`
- `structure_time_bonus`
- `rig_material_bonus`
- `rig_time_bonus`

Inputs are strict: numeric strings and booleans are not accepted as integers.
The snapshots of the old GPT instructions require clarification for modifiers;
this adapter exposes the implementation's zero defaults and reports returned
inputs rather than importing those GPT-specific instruction rules.
No URL, mode, internal route, station ID or production-region parameter is exposed.

Example MCP arguments:

```json
{"request":{"name":"Carbon Fiber","quantity":200,"blueprint_me":0}}
```

All five tools advertise readOnlyHint=true, destructiveHint=false,
idempotentHint=true and openWorldHint=true (they access an external backend).

## Results, limits and errors

Successful structuredContent is `{ "data": <unchanged backend object>,
"warnings": [<adapter context>] }`. The SDK also emits a JSON text representation
for compatible clients. All original fields, including nested manufacturing and
reaction activities, null costs, missing_prices, incomplete_reasons, plans and
backend warnings are retained. No extra pricing logic or totals are introduced.
The adapter adds an explicit warning for incomplete costs (and a separate warning
if completeness is absent). Original incomplete results stay successful data
with warnings; they are never treated as zero-cost opportunities.

Each call makes one bounded GET, with a 10-second connection timeout,
30-second inactivity timeout and 120-second total deadline. Decoded response
bodies are limited to 1 MiB. Oversized responses fail explicitly instead of
returning truncated trees or dropping missing-price fields. Smaller top/days
or production requests can reduce response size. No automatic retries, redirects
or result caching are introduced. The upstream URL is fixed, not user-controlled.

HTTP errors (including their original JSON), backend `error` objects even with
HTTP 200, invalid/non-object/non-finite JSON, timeouts, connection failures and
oversized responses become MCP tool errors (`isError: true` on the wire).
Non-JSON errors include HTTP status and a bounded 1000-byte excerpt. SDK protocol
validation handles invalid tool arguments. No error is converted to an empty
success result.

## Backend limitations retained

- Production prices are cached cross-region Fuzzwork sell percentiles, not a
  selected market, executable fill quote or net profit after fees and hauling.
- History is regional; days selects available records, not a filled calendar
  window. Its optional current comparison may use cached cross-region prices.
- Recursive trees stop at the backend depth limit. All incompleteness survives.
- Fit costs enter the total but the comparison quote covers only the primary
  item; a warning is added when fit is supplied. Existing fit parsing is unchanged.
- Manufacturing efficiency and reaction modifier rules remain backend-owned.
- Unknown production items can return nonbuildable/incomplete results with 200.
- Material requirements use the existing raw and hybrid plan behavior. Incomplete
  plans must not be presented as complete shopping lists.
- No candidate discovery, scanning, job timing calculation or new profitability
  model is provided. Live data and upstream availability can change between calls.

## Verification

Install both root and adapter requirements for the combined suite:

```sh
python -m pip install -r requirements.txt -r mcp_adapter/requirements.txt
python -m unittest discover -s tests -v
```

The live contract test is opt-in. In PowerShell:

```powershell
$env:EVE_MCP_LIVE='1'
python -m unittest discover -s tests -v
```

The protocol tests use the real SDK Streamable HTTP ASGI app, JSON-RPC
initialization (2025-11-25 compatibility), initialized notification, discovery,
and tools/call. Live checks send those calls through the adapter to the hosted
backend; they require no database access from the adapter. Deterministic tests
cover all translations, strict validation, nested incomplete data, transport and
backend errors, total deadlines and size limits. The checked-in discovery schema
is compared against the actual server to keep this interface reviewable.

Verified on 2026-09-05: 45 offline tests passed (all 37 existing backend tests
included), with the one opt-in live test skipped in the offline run. Separately,
all three HTTP contract tests passed with live checks enabled: all five tools,
Drake orders/history, Antimatter Charge S manufacturing, Carbon Fiber reactions,
and a deliberately unresolved item preserving false completeness and missing_prices.
The official SDK Client also connected to the running loopback server over TCP
and discovered the five tools. The local test server was stopped afterward.

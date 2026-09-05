import asyncio
import json
from pathlib import Path
import unittest
import httpx
from mcp_adapter.backend_client import BackendClient, BackendError
from mcp_adapter.server import create_server
from mcp.server.mcpserver.exceptions import ToolError


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_matches_documented_schema(self):
        tools = await create_server().list_tools()
        actual = [t.model_dump(by_alias=True, exclude_none=True) for t in tools]
        expected = json.loads((Path(__file__).resolve().parents[1] / 'mcp_adapter/tool-schemas.json').read_text())
        self.assertEqual(actual, expected)

    async def test_translation_and_lossless_incomplete_results(self):
        payload = {"cost_complete": False, "total_cost": None, "missing_prices": ["Raw"],
                   "incomplete_reasons": ["Missing material prices"], "build_vs_buy": None,
                   "materials": [{"components": {"cost_complete": False, "missing_prices": ["Raw"], "activity": "reaction"}}]}
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json=payload)
        server = create_server(BackendClient(transport=httpx.MockTransport(respond)))
        cases = [
            ("get_sell_orders", {"type_id": 24698, "system_name": "Jita", "cheapest": True}, "/api/main", "market"),
            ("get_market_history", {"name": "Drake", "region_name": "The Forge", "days": 2}, "/market-history", None),
            ("get_production_tree", {"name": "Carbon Fiber", "quantity": 2, "blueprint_me": 10}, "/api/main", "tree"),
            ("get_material_requirements", {"name": "Drake"}, "/api/main", "raw"),
            ("analyze_build_vs_buy", {"name": "Drake", "fit": "1MN Afterburner I"}, "/api/main", "tree"),
        ]
        for tool, args, path, mode in cases:
            with self.subTest(tool=tool):
                result = await server.call_tool(tool, {"request": args})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["data"], payload)
                request = calls[-1]
                self.assertEqual(request.method, "GET")
                self.assertEqual(request.url.path, path)
                self.assertEqual(request.url.params.get("mode"), mode)
                self.assertNotIn("_route", request.url.params)
                if mode in ("tree", "raw"):
                    self.assertTrue(any("incomplete" in x for x in result.structured_content["warnings"]))
        self.assertEqual(calls[0].url.params['typeId'], '24698')
        self.assertEqual(calls[0].url.params['scan'], 'Jita')
        self.assertEqual(calls[0].url.params['cheapest'], 'true')
        self.assertEqual(calls[1].url.params['days'], '2')
        self.assertEqual(calls[2].url.params['blueprint_me'], '10')
        self.assertEqual(calls[2].url.params['quantity'], '2')

    async def test_invalid_inputs_do_not_call_backend(self):
        def fail(request):
            self.fail("invalid input reached backend")
        server = create_server(BackendClient(transport=httpx.MockTransport(fail)))
        cases = [("get_sell_orders", {}), ("get_sell_orders", {"name": "Drake", "top": 101}),
                 ("get_sell_orders", {"type_id": True}),
                 ("get_market_history", {"name": "Drake", "region_name": "Jita", "days": 0}),
                 ("get_production_tree", {"name": "  "}),
                 ("get_production_tree", {"name": "Drake", "blueprint_me": "10"}),
                 ("get_production_tree", {"name": "Drake", "_route": "history"})]
        for tool, args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ToolError):
                    await server.call_tool(tool, {"request": args})

    async def test_errors_are_mcp_errors_with_backend_details(self):
        for status in (400, 404, 429, 500, 502, 503, 504, 200):
            server = create_server(BackendClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"error": "ESI unavailable", "missing_prices": ["Raw"]}))))
            with self.assertRaises(ToolError) as caught:
                await server.call_tool("get_sell_orders", {"request": {"name": "Drake"}})
            text = str(caught.exception)
            self.assertIn(str(status), text)
            self.assertIn("ESI unavailable", text)
            self.assertIn("Raw", text)

    async def test_size_invalid_json_shape_redirect_and_transport_errors(self):
        responses = [httpx.Response(200, content=b'x' * 101),
                     httpx.Response(200, content=b'{bad'), httpx.Response(200, json=[]),
                     httpx.Response(200, content=b'{"price":NaN}'),
                     httpx.Response(200, content=b'{"price":1e999}'),
                     httpx.Response(302, headers={"location": "https://example.com"}, json={})]
        for response in responses:
            client = BackendClient(max_bytes=100, transport=httpx.MockTransport(lambda r: response))
            with self.assertRaises(BackendError):
                await client.get('/api/main', {})
        for error in (httpx.ReadTimeout('timeout'), httpx.ConnectError('offline')):
            def fail(request):
                raise error
            with self.assertRaises(BackendError):
                await BackendClient(transport=httpx.MockTransport(fail)).get('/api/main', {})

    async def test_total_deadline(self):
        async def slow(request):
            await asyncio.sleep(0.1)
            return httpx.Response(200, json={})
        with self.assertRaisesRegex(BackendError, 'timed out'):
            await BackendClient(timeout_seconds=0.01, transport=httpx.MockTransport(slow)).get('/api/main', {})

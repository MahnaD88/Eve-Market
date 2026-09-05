"""Real Streamable HTTP protocol tests; live backend checks opt in with EVE_MCP_LIVE=1."""
import json
import os
import unittest
import httpx
from starlette.testclient import TestClient
from mcp_adapter.backend_client import BackendClient
from mcp_adapter.server import create_server

TOOLS = {"get_sell_orders", "get_market_history", "get_production_tree",
         "get_material_requirements", "analyze_build_vs_buy"}

class ProtocolTests(unittest.TestCase):
    def connect(self, backend=None):
        server = create_server(backend)
        client = self.enterContext(TestClient(server.streamable_http_app(
            stateless_http=True, json_response=True), base_url="http://127.0.0.1:8000"))
        self.headers = {"Accept": "application/json, text/event-stream"}
        self.client = client
        initialized = self.rpc("initialize", {"protocolVersion": "2025-11-25",
            "capabilities": {}, "clientInfo": {"name": "eve-contract-test", "version": "1"}})
        self.assertEqual(initialized['serverInfo']['name'], 'eve-industry')
        self.headers['MCP-Protocol-Version'] = initialized['protocolVersion']
        notification = client.post('/mcp', headers=self.headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(notification.status_code, 202)

    def rpc(self, method, params):
        response = self.client.post('/mcp', headers=self.headers,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertNotIn('error', data, data)
        return data['result']

    def test_initialization_discovery_and_http_tool_result(self):
        payload = {"cost_complete": False, "total_cost": None, "missing_prices": ["Raw"],
                   "incomplete_reasons": ["Missing material prices"], "build_vs_buy": None}
        self.connect(BackendClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))))
        tools = self.rpc('tools/list', {})['tools']
        self.assertEqual({t['name'] for t in tools}, TOOLS)
        for tool in tools:
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertFalse(tool['annotations']['destructiveHint'])
            self.assertIn('outputSchema', tool)
            self.assertNotIn('_route', json.dumps(tool['inputSchema']))
            self.assertEqual(tool['inputSchema']['required'], ['request'])
        result = self.rpc('tools/call', {'name': 'get_production_tree', 'arguments': {'request': {'name': 'Carbon Fiber'}}})
        self.assertFalse(result.get('isError', False))
        self.assertEqual(result['structuredContent']['data'], payload)
        self.assertTrue(result['structuredContent']['warnings'])

    def test_http_errors_are_not_successful_empty_results(self):
        self.connect(BackendClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(503, json={"error": "ESI unavailable"}))))
        result = self.rpc('tools/call', {'name': 'get_sell_orders', 'arguments': {'request': {'name': 'Drake'}}})
        self.assertTrue(result['isError'])
        self.assertIn('503', result['content'][0]['text'])
        self.assertIn('ESI unavailable', result['content'][0]['text'])

    @unittest.skipUnless(os.environ.get('EVE_MCP_LIVE') == '1', 'Set EVE_MCP_LIVE=1 for hosted backend checks')
    def test_all_five_tools_live_manufacturing_reaction_and_missing_price(self):
        self.connect()
        self.assertEqual({t['name'] for t in self.rpc('tools/list', {})['tools']}, TOOLS)
        cases = [
            ('get_sell_orders', {'name': 'Drake', 'system_name': 'Jita', 'top': 2}),
            ('get_market_history', {'name': 'Drake', 'region_name': 'The Forge', 'days': 2}),
            ('get_production_tree', {'name': 'Antimatter Charge S'}),
            ('get_material_requirements', {'name': 'Antimatter Charge S'}),
            ('analyze_build_vs_buy', {'name': 'Carbon Fiber'}),
            ('get_production_tree', {'name': 'EVE MCP missing-price test item 000000'}),
        ]
        for tool, args in cases:
            with self.subTest(tool=tool, name=args['name']):
                result = self.rpc('tools/call', {'name': tool, 'arguments': {'request': args}})
                self.assertFalse(result.get('isError', False), result)
                data = result['structuredContent']['data']
                print('LIVE', tool, args['name'], 'status=', data.get('status'),
                      'activity=', data.get('activity'), 'cost_complete=', data.get('cost_complete'), flush=True)
                if tool == 'get_sell_orders':
                    self.assertEqual(data['status'], 'ok')
                    self.assertTrue(data['orders'])
                    self.assertLessEqual(len(data['orders']), 2)
                elif tool == 'get_market_history':
                    self.assertEqual(data['status'], 'ok')
                    self.assertTrue(data['history'])
                    self.assertLessEqual(len(data['history']), 2)
                elif args['name'].startswith('EVE MCP'):
                    self.assertFalse(data['cost_complete'])
                    self.assertIsNone(data['total_cost'])
                    self.assertIn(args['name'], data['missing_prices'])
                elif tool == 'get_material_requirements':
                    self.assertTrue(data['raw_materials'])
                    self.assertIn('cost_complete', data)
                else:
                    self.assertTrue(data['buildable'])
                    self.assertEqual(data['activity'], 'reaction' if args['name'] == 'Carbon Fiber' else 'manufacturing')
                    self.assertIn('cost_complete', data)


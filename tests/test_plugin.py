import asyncio
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import httpx
import yaml
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient
from mcp_adapter.backend_client import BackendClient
from mcp_adapter.asgi import create_app
from scripts.configure_plugin_connection import configure
from scripts.prepare_mcp_deployment import prepare

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/eve-industry"


class PluginTests(unittest.TestCase):
    def test_package_manifest_skills_and_references(self):
        manifest = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], PLUGIN.name)
        self.assertEqual(manifest['apps'], './.app.json')
        self.assertNotIn('mcpServers', manifest)
        self.assertFalse((PLUGIN / '.mcp.json').exists())
        self.assertEqual(json.loads((PLUGIN / '.app.json').read_text()), {'apps': {'eve-industry': {'id': 'asdk_app_6a9db8c900e08191bd9953ac25247730', 'required': True}}})
        connection = json.loads((PLUGIN / '.mcp.local.json').read_text())
        self.assertEqual(connection['mcpServers']['eve-industry']['url'], 'https://project-jm8k1.vercel.app/mcp')
        skills = sorted((PLUGIN / 'skills').glob('*/SKILL.md'))
        self.assertEqual(len(skills), 3)
        for path in skills:
            text = path.read_text(encoding='utf-8')
            front = yaml.safe_load(text.split('---', 2)[1])
            self.assertEqual(front['name'], path.parent.name)
            self.assertTrue(front['description'])
            for relative in re.findall(r'\]\(([^)]+)\)', text):
                resolved = (path.parent / relative).resolve()
                self.assertTrue(resolved.is_relative_to(PLUGIN.resolve()))
                self.assertTrue(resolved.is_file(), relative)
        marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual(marketplace['plugins'][0]['source']['path'], './plugins/eve-industry')

    def test_real_connection_binding_disables_duplicate_local_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / 'eve-industry'
            shutil.copytree(PLUGIN, copy)
            (copy / '.mcp.local.json').rename(copy / '.mcp.json')
            original = (copy / '.mcp.json').read_bytes()
            configure('asdk_app_test_fixture', copy)
            manifest = json.loads((copy / '.codex-plugin/plugin.json').read_text())
            self.assertEqual(manifest['apps'], './.app.json')
            self.assertNotIn('mcpServers', manifest)
            self.assertFalse((copy / '.mcp.json').exists())
            self.assertEqual((copy / '.mcp.local.json').read_bytes(), original)
            self.assertEqual(json.loads((copy / '.app.json').read_text())['apps']['eve-industry'],
                             {'id': 'asdk_app_test_fixture', 'required': True})
            configure('asdk_app_test_fixture', copy)  # Idempotent rebind.
            for invalid in ('not-a-registered-id', 'plugin_asdk_app_test', 'asdk_app_v_test', 'asdk_app_'):
                with self.assertRaises(ValueError):
                    configure(invalid, copy)

    def test_custom_connection_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / 'eve-industry'
            shutil.copytree(PLUGIN, copy)
            (copy / '.app.json').unlink()
            (copy / '.mcp.local.json').unlink()
            (copy / '.mcp.json').write_text('{"custom":true}')
            with self.assertRaises(ValueError):
                configure('asdk_app_test_fixture', copy)
            self.assertFalse((copy / '.app.json').exists())
            self.assertEqual((copy / '.mcp.json').read_text(), '{"custom":true}')

    def test_deployment_staging_excludes_existing_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            result = prepare(Path(temp) / 'standalone')
            self.assertTrue((result / 'mcp_adapter/server.py').is_file())
            self.assertTrue((result / 'app.py').is_file())
            self.assertFalse((result / 'api').exists())
            self.assertFalse(list(result.rglob('*.sqlite')))
            self.assertFalse(list(result.rglob('.env*')))
            self.assertEqual((result / 'mcp_adapter/server.py').read_bytes(),
                             (ROOT / 'mcp_adapter/server.py').read_bytes())
            with self.assertRaises(ValueError):
                prepare(result)

    def test_forward_trace_schema_and_minimum_call_counts(self):
        traces = json.loads((ROOT / 'tests/fixtures/plugin_skill_traces.json').read_text())['traces']
        schemas = {tool['name']: tool['inputSchema'] for tool in json.loads(
            (ROOT / 'mcp_adapter/tool-schemas.json').read_text())}
        expected = {'price':['get_sell_orders'], 'history':['get_market_history'],
            'recipe':['get_production_tree'], 'raw_unknown_modifiers':[],
            'build_buy':['analyze_build_vs_buy'],
            'worth_making':['analyze_build_vs_buy','get_sell_orders','get_market_history'],
            'incomplete':[], 'unsupported_scan':[]}
        for trace in traces:
            with self.subTest(case=trace['id']):
                self.assertEqual([call['tool'] for call in trace['calls']], expected[trace['id']])
                for call in trace['calls'] + trace.get('after_zero_baseline', []):
                    Draft202012Validator(schemas[call['tool']]).validate(call['arguments'])
        self.assertTrue(next(t for t in traces if t['id']=='raw_unknown_modifiers')['clarification'])
        self.assertEqual(next(t for t in traces if t['id']=='raw_unknown_modifiers')['after_zero_baseline'][0]['tool'], 'get_material_requirements')

    def test_asgi_entrypoint_initialization_discovery_and_missing_cost(self):
        data = {'cost_complete':False, 'total_cost':None, 'missing_prices':['Hydrocarbons'],
                'incomplete_reasons':['Missing material prices'], 'build_vs_buy':None}
        backend = BackendClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=data)))
        with TestClient(create_app(backend, ['eve-mcp.test']), base_url='https://eve-mcp.test') as client:
            headers = {'Accept':'application/json, text/event-stream'}
            def rpc(method, params):
                response = client.post('/mcp', headers=headers, json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
                self.assertEqual(response.status_code,200,response.text)
                return response.json()['result']
            result = rpc('initialize', {'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'plugin-test','version':'1'}})
            headers['MCP-Protocol-Version'] = result['protocolVersion']
            tools = rpc('tools/list', {})['tools']
            self.assertEqual(len(tools),5)
            result = rpc('tools/call', {'name':'analyze_build_vs_buy','arguments':{'request':{'name':'Carbon Fiber'}}})
            self.assertFalse(result.get('isError',False))
            self.assertEqual(result['structuredContent']['data'],data)
            self.assertTrue(any('incomplete' in warning for warning in result['structuredContent']['warnings']))
            blocked = client.post('/mcp', headers={**headers,'Host':'unexpected.test'},json={})
            self.assertEqual(blocked.status_code,421)
            blocked = client.post('/mcp', headers={**headers,'Origin':'https://unexpected.test'},json={})
            self.assertEqual(blocked.status_code,403)
        with self.assertRaises(ValueError):
            create_app(public_hosts=['https://invalid.test/mcp'])

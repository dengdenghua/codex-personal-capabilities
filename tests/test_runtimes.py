import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_manager',ROOT/'scripts/runtime_manager.py')
rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)

class RuntimeTests(unittest.TestCase):
    def test_node_version_matches_rea_engine_range(self):
        for version in ['22.23.4','24.22.1','26.12.1','27.0.0']:self.assertTrue(rt.node_supported(version))
        for version in ['22.23.3','24.19.0','25.0.0','26.12.0']:self.assertFalse(rt.node_supported(version))
    def test_upgrade_repairs_managed_defaults(self):
        old={'servers':{'rea':{'managed_by':'codex-personal-capabilities','env':{'REA_MCP_INPUT_SCHEMA_PROFILE':'standard','CUSTOM':'preserved'}}}}
        new,_=rt.merge_config(old,{'rea':{'managed_by':'codex-personal-capabilities','env':{'REA_MCP_INPUT_SCHEMA_PROFILE':'compact'}}})
        self.assertEqual(new['servers']['rea']['env'],{'REA_MCP_INPUT_SCHEMA_PROFILE':'compact','CUSTOM':'preserved'})
    def test_no_private_state_in_repo(self):
        with self.assertRaises(ValueError):rt.safe_outside_repo(ROOT/'private-data')
    def test_preserve_custom_servers(self):
        old={'servers':{'demo':{'command':'custom','env':{'PRIVATE_SETTING':'local'}}},'other':42}
        new,preserved=rt.merge_config(old,{'demo':{'command':'managed'}})
        self.assertEqual(new,old);self.assertEqual(preserved,['demo'])
    def test_upgrade_managed_preserves_local_settings(self):
        old={'servers':{'demo':{'managed_by':'codex-personal-capabilities','command':'old','env':{'PRIVATE_SETTING':'local'}}}}
        new,_=rt.merge_config(old,{'demo':{'managed_by':'codex-personal-capabilities','command':'new','env':{'NEW':'value'}}})
        self.assertEqual(new['servers']['demo']['command'],'new')
        self.assertEqual(new['servers']['demo']['env']['PRIVATE_SETTING'],'local')
    def test_all_sources_bundled(self):
        for name,service in rt.SERVERS.items():
            root,files=rt.source_files(service)
            self.assertTrue(files,name)
            if 'requirements' in service:self.assertTrue((root/service['requirements']).is_file())
            if 'entry' in service:self.assertTrue((root/service['entry']).is_file())
    def test_probe_never_calls_a_tool(self):
        code='''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if r['method']=='initialize':out={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fake','version':'1'}}
 elif r['method']=='tools/list':out={'tools':[{'name':'example'}]}
 elif r['method']=='notifications/initialized':continue
 else:raise RuntimeError('unexpected native operation')
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':out}),flush=True)
'''
        result=rt.probe({'command':sys.executable,'args':['-u','-c',code]},timeout=3)
        self.assertEqual(result['tools'],1);self.assertEqual(result['native_operations'],'not_called')
    def test_missing_command_report(self):
        with patch.object(rt,'native_discovery',return_value={}):
            result=rt.doctor({'servers':{'blender_official':{'command':'nonexistent-personal-mcp-command','args':[]}}},['blender_official'])
        self.assertEqual(result['services']['blender_official']['status'],'failed')
    def test_windows_only_report(self):
        with patch.object(rt.os,'name','posix'),patch.object(rt,'native_discovery',return_value={}):
            report=rt.doctor({},['solidworks_local'])
        self.assertEqual(report['services']['solidworks_local']['status'],'unsupported_platform')
    def test_private_sw_state_path(self):
        source=(ROOT/'plugins/solidworks-control/server/jobs.py').read_text(encoding='utf8')
        self.assertIn("JOBS=DATA/'jobs'",source)
        self.assertNotIn("JOBS=ROOT/'jobs'",source)

if __name__=='__main__':unittest.main()

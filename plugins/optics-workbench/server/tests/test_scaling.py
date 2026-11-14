import copy
import math
import tempfile
import unittest
from unittest.mock import patch
from optics_workbench.core import Workbench
from optics_workbench.calculations import template_parameters
from optics_workbench.scene import default_scene,trace_scene
from optics_workbench.scaling import scale_design,scale_aspheric_coefficients
from optics_workbench.mcp_server import MCPServer

class ScalingTests(unittest.TestCase):
    def test_full_homothety_preserves_normalized_ray_paths_and_angles(self):
        p=template_parameters('dlp');s=default_scene(p);factor=1.7
        scaled=scale_design(p,s,factor,'all');a=trace_scene(s);b=trace_scene(scaled['scene'])
        for r,t in zip(a['rays'],b['rays']):
            self.assertEqual(r['status'],t['status']);self.assertEqual(r['blocked_by'],t['blocked_by'])
            self.assertEqual(r['angle_deg'],t['angle_deg'])
            for x,y in zip(r['points'],t['points']):
                self.assertAlmostEqual(x['z_mm']*factor,y['z_mm'],9)
                self.assertAlmostEqual(x['y_mm']*factor,y['y_mm'],9)
        self.assertEqual(s,default_scene(p))
        self.assertEqual(scaled['parameters']['wavelength_nm'],p['wavelength_nm'])
        self.assertEqual(scaled['parameters']['source_lumens'],p['source_lumens'])
        self.assertAlmostEqual(scaled['parameters']['relay_efl_mm']/scaled['parameters']['cell_efl_mm'],p['relay_efl_mm']/p['cell_efl_mm'])

    def test_fixed_source_and_nonzero_anchor(self):
        p=template_parameters('dlp');s=default_scene(p)
        for e in s['elements']:e['z_mm']+=10;e['y_mm']+=2
        out=scale_design(p,s,2,'fixed')
        self.assertEqual(out['scene']['elements'][0],s['elements'][0])
        self.assertEqual(out['parameters']['source_width_mm'],p['source_width_mm'])
        self.assertEqual(out['parameters']['source_height_mm'],p['source_height_mm'])
        self.assertAlmostEqual(out['scene']['elements'][1]['z_mm']-10,2*(s['elements'][1]['z_mm']-10))
        self.assertEqual(out['scene']['rays'],s['rays'])

    def test_asphere_sag_dimensional_transform(self):
        coefficients={4:1e-5,6:-2e-8,8:3e-11};factor=1.5
        scaled=scale_aspheric_coefficients(coefficients,factor)
        for r in [.1,1,5,10]:
            old=sum(a*r**m for m,a in coefficients.items())
            new=sum(a*(factor*r)**m for m,a in scaled.items())
            self.assertAlmostEqual(factor*old,new,13)

    def test_invalid_factors_and_scene_bounds_are_rejected(self):
        p=template_parameters('dlp');s=default_scene(p)
        for factor in [True,0,-1,float('nan'),float('inf'),101,'2']:
            with self.assertRaises(ValueError):scale_design(p,s,factor)
        with self.assertRaises(ValueError):scale_design(p,s,2,'unknown')
        s['elements'][-1]['z_mm']=9e6
        with self.assertRaises(ValueError):scale_design(p,s,2)

class StoredScalingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Workbench(data_dir=self.tmp.name)
        self.p=self.w.project(self.w.projects()[0]['id'])
    def tearDown(self):self.tmp.cleanup()

    def test_preview_unsaved_clone_has_independent_identity_and_no_component_claim(self):
        original=copy.deepcopy(self.p);n=len(self.w.projects())
        preview=self.w.preview_scale(self.p['id'],1,1.5)
        self.assertEqual(self.w.project(self.p['id']),original);self.assertEqual(len(self.w.projects()),n)
        saved=self.w.clone_scaled(self.p['id'],1,1.5)['project']
        self.assertNotEqual(saved['id'],self.p['id']);self.assertEqual(saved['version'],1)
        self.assertEqual(saved['scene'],preview['draft']['scene']);self.assertEqual(saved['selected_components'],{})
        self.assertEqual(self.w.project(self.p['id']),original)

    def test_source_version_rechecked_inside_clone_transaction(self):
        prepared=self.w.preview_scale(self.p['id'],1,1.5)
        changed=copy.deepcopy(self.p);changed['notes']='concurrent source edit';self.w.save_project(changed)
        with patch.object(self.w,'preview_scale',return_value=prepared):
            with self.assertRaisesRegex(ValueError,'来源原型已更新'):self.w.clone_scaled(self.p['id'],1,1.5)
        self.assertEqual(len(self.w.projects()),1)
        self.assertEqual(self.w.project(self.p['id'])['version'],2)

    def test_fresh_mcp_preview_and_clone(self):
        server=MCPServer(self.w)
        server.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'scaling-test','version':'1'}}})
        server.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
        args={'project_id':self.p['id'],'version':1,'factor':1.5,'source_mode':'all'}
        for i,name in enumerate(['optics_preview_scaled_prototype','optics_clone_scaled_prototype'],2):
            r=server.handle({'jsonrpc':'2.0','id':i,'method':'tools/call','params':{'name':name,'arguments':args}})
            self.assertNotIn('error',r);self.assertFalse(r['result'].get('isError',False),r)
        self.assertEqual(len(self.w.projects()),2)

if __name__=='__main__':unittest.main()

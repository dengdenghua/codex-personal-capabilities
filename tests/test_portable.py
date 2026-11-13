import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    s=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
launch=load('launch_mcp');validate=load('validate')
class PortableTests(unittest.TestCase):
    def test_missing_runtime(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):launch.resolve('unknown',Path(t)/'missing.json')
    def test_no_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'settings.json';p.write_text(json.dumps({'servers':{'demo':{'command':'python','args':['a b','$(no)','x;y'],'env':{'TEST':'ok'}}}}))
            argv,env,cwd=launch.resolve('demo',p)
            self.assertEqual(argv,['python','a b','$(no)','x;y']);self.assertEqual(env['TEST'],'ok');self.assertIsNone(cwd)
    def test_invalid_config(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'settings.json';p.write_text(json.dumps({'servers':{'demo':{'command':'python','args':'not-an-array'}}}))
            with self.assertRaises(ValueError):launch.resolve('demo',p)
    def test_private_files_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'data.sqlite').write_text('private');(p/'auth.json').write_text('{}')
            self.assertEqual(len(validate.problems(p)),2)
    def test_token_detection(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'a.txt').write_text('gh'+'p_'+'A'*36)
            self.assertTrue(validate.problems(p))
    def test_no_original_private_path(self):
        self.assertEqual(validate.problems(),[])
if __name__=='__main__':unittest.main()

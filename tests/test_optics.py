import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'plugins/optics-workbench/server'))
import optics_private as private
from optics_workbench.core import Workbench
from optics_workbench.mcp_server import MCPServer

class OpticalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.source=self.base/'source';self.source.mkdir()
        self.lens=self.source/'lens';self.lens.mkdir()
        self.db=sqlite3.connect(self.lens/'lens_library.sqlite')
        self.db.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE sources(id TEXT,sha256 TEXT,local_path TEXT,extension TEXT,status TEXT);
CREATE TABLE locations(id INTEGER,source_id TEXT,original_path TEXT);
CREATE TABLE cases(id TEXT);
CREATE TABLE knowledge(id TEXT,title TEXT,topic TEXT,statement TEXT,conditions TEXT);
INSERT INTO knowledge VALUES ('k1','合成双高斯','测试','仅供回归','非真实案例');
INSERT INTO sources VALUES ('s1','synthetic','historical.txt','.txt','indexed');
INSERT INTO locations VALUES (1,'s1','historical.txt');''');self.db.commit()
        self.memory=self.source/'memory.sqlite3'
        with closing(sqlite3.connect(self.memory)) as db:
            db.execute('CREATE TABLE entries(id TEXT,scope TEXT,text TEXT,payload TEXT,recorded_at TEXT)')
            db.execute('INSERT INTO entries VALUES (?,?,?,?,?)',('m1','仅本测试','中文续接',json.dumps({'kind':'open_question','text':'中文续接'}),'2026-01-01'))
            db.commit()
        self.original=self.source/'原文.txt';self.original.write_text('合成证据\n',encoding='utf8')
        self.digest=private.sha(self.original)
        self.wb=Workbench(data_dir=self.source/'data')
        self.mapping=self.source/'mapping.json'
        private.write(self.mapping,{'objects':{self.digest:{'path':str(self.original),'sha256':self.digest}}})
        self.wb.config.update(lens_library_root=str(self.lens),workflow_memory=str(self.memory),path_map=str(self.mapping))
    def tearDown(self):self.db.close();self.temp.cleanup()
    def call(self,name,args=None):
        server=MCPServer(self.wb,read_only=True)
        server.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'tests','version':'1'}}})
        server.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
        reply=server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args or {}}})
        self.assertFalse(reply['result']['isError'],reply)
        return json.loads(reply['result']['content'][0]['text'])['data']
    def test_all_five_new_mcp_routes_use_real_data(self):
        self.assertEqual(self.call('optics_private_status')['lens_sources'],1)
        self.assertEqual(self.call('optics_search_lens',{'kind':'knowledge','query':'双高斯'})['total'],1)
        self.assertEqual(self.call('optics_lens_detail',{'kind':'documents','identifier':'s1'})['locations'][0]['original_path'],'historical.txt')
        self.assertEqual(self.call('optics_search_workflow_memory',{'query':'中文'})['graph_sync'],'not_performed')
        self.assertTrue(self.call('optics_resolve_source',{'identity':self.digest})['verified'])
    def make_backup(self,complete=True):
        files=[]
        for p,target in [(self.lens/'lens_library.sqlite','lens/lens_library.sqlite'),(self.memory,'workflow-memory/memory.sqlite3'),(self.original,'evidence/原文.txt'),(self.source/'data/workbench.sqlite3','workbench/data/workbench.sqlite3')]:
            files.append({'source':str(p),'target':target,'aliases':[str(p)],'expected_sha256':None,'bytes':p.stat().st_size})
        plan=self.base/'plan.json';archive=self.base/'backup.zip'
        private.write(plan,{'files':files,'complete':complete,'missing':[] if complete else [{'id':'missing'}],'workbench_config':{}})
        private.backup(plan,archive);return archive
    def test_sqlite_wal_backup_and_relocated_restore(self):
        archive=self.make_backup();dest=self.base/'restored';private.restore(archive,dest)
        self.assertEqual(private.database_counts(dest/'lens/lens_library.sqlite')['knowledge'],1)
        self.assertEqual((dest/'evidence/原文.txt').read_text(encoding='utf8'),'合成证据\n')
        mapping=private.read(dest/'path-map.json');self.assertEqual(mapping['paths'][str(self.original)]['path'],str(dest/'evidence/原文.txt'))
        before=private.database_counts(dest/'workbench/data/workbench.sqlite3')
        restored=Workbench(config_path=dest/'workbench/config.json')
        self.assertEqual(before,private.database_counts(restored.db_path))
    def test_restore_does_not_overwrite_existing_directory(self):
        archive=self.make_backup()
        with self.assertRaises(FileExistsError):private.restore(archive,self.source)
    def test_incomplete_backup_requires_explicit_partial_restore(self):
        archive=self.make_backup(False)
        with self.assertRaises(ValueError):private.restore(archive,self.base/'restored')
    def test_archive_corruption_rejected(self):
        archive=self.make_backup()
        with archive.open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):private.restore(archive,self.base/'restored')
    def test_zip_traversal_rejected_even_with_matching_outer_hash(self):
        archive=self.make_backup()
        with zipfile.ZipFile(archive,'a') as z:z.writestr('../escape','no')
        private.write(archive.with_suffix('.zip.sha256.json'),{'sha256':private.sha(archive)})
        with self.assertRaises(ValueError):private.restore(archive,self.base/'restored')
    def test_private_destination_inside_git_rejected(self):
        with self.assertRaises(ValueError):private.outside(ROOT/'backup.zip')
    def test_rescan_distinguishes_different_roots_with_same_relative_name(self):
        first=self.base/'first';second=self.base/'second';first.mkdir();second.mkdir()
        a=first/'source.txt';b=second/'source.txt';a.write_bytes(b'first');b.write_bytes(b'other')
        plan=self.base/'plan.json'
        private.write(plan,{'files':[{'source':str(a),'target':'evidence/root-0/source.txt','aliases':[str(a)],'expected_sha256':private.sha(a),'bytes':5}],
                           'complete':False,'missing':[{'id':'old','sha256':private.sha(b),'bytes':None,'paths':[r'C:\historical\source.txt']}]})
        result=private.rescan(plan,[str(second)])
        self.assertTrue(result['complete'])
        self.assertEqual(len({i['target'] for i in result['files']}),2)
        self.assertEqual(result['files'][1]['expected_sha256'],private.sha(b))
    def test_changed_source_identity_stops_backup(self):
        plan=self.base/'plan.json';private.write(plan,{'complete':True,'missing':[],'workbench_config':{},'files':[{'source':str(self.original),'target':'evidence.txt','aliases':[],'expected_sha256':'0'*64}]})
        with self.assertRaises(ValueError):private.backup(plan,self.base/'bad.zip')
    def test_unregistered_source_and_mutation_rejected(self):
        from optics_workbench.private_library import resolve
        with self.assertRaises(ValueError):resolve(self.wb,str(self.base/'unregistered'))
        self.original.write_text('changed')
        with self.assertRaises(ValueError):resolve(self.wb,self.digest)
    def test_lens_copy_uses_identity_when_historical_path_has_multiple_versions(self):
        correct=self.base/'correct.zmx';correct.write_bytes(b'UNIT MM\nSURF 0\n')
        wrong=self.base/'wrong.zmx';wrong.write_bytes(b'other version')
        digest=private.sha(correct);mapping=self.base/'lens-mapping.json'
        private.write(mapping,{'paths':{'old.zmx':{'path':str(wrong)}},'objects':{digest:{'path':str(correct)}}})
        detail={'source':{'local_path':'old.zmx','sha256':digest},'title':'Synthetic','unit':'MM'}
        home=self.base/'codex';private.write(home/'lens-toolkit.local.json',{'library_root':str(self.lens),'path_map':str(mapping)})
        paths=['plugins/lens-toolkit/skills/lens-evidence-search/scripts/library.py','plugins/personal-skills/skills/lens-evidence-search/scripts/library.py','plugins/optics-workbench/server/optics_workbench/lens_library.py']
        for n,path in enumerate(paths):
            with self.subTest(package=path):
                spec=importlib.util.spec_from_file_location('lens_helper_'+str(n),ROOT/path)
                library=importlib.util.module_from_spec(spec);spec.loader.exec_module(library)
                with patch.dict('os.environ',{'CODEX_HOME':str(home),'LENS_PATH_MAP':'','LENS_LIBRARY_ROOT':''}),patch.object(library,'detail',return_value=detail):
                    self.assertEqual(library.resolve_root(),self.lens)
                    result=library.prepare_case(None,'synthetic',self.base/('working-copy-'+str(n)))
                self.assertEqual(private.sha(Path(result['directory'])/'prescription_source.zmx'),digest)
        self.assertEqual(detail['source']['local_path'],'old.zmx')
    def test_retry_only_accepts_unchanged_same_archive(self):
        archive=self.make_backup();dest=self.base/'restored';private.restore(archive,dest)
        private.verify_restored(archive,dest)
        (dest/'evidence/原文.txt').write_text('changed')
        with self.assertRaises(ValueError):private.verify_restored(archive,dest)
    def test_private_manifest_cannot_pass_public_validation(self):
        import validate
        p=self.base/'renamed.json';private.write(p,{'format':'optics-private-plan-v1','files':[]})
        self.assertTrue(any('private optical manifest' in x for x in validate.problems(self.base)))
    def test_partial_recovery_is_explicit_and_reports_gaps(self):
        archive=self.make_backup(False);dest=self.base/'restored';private.restore(archive,dest,allow_incomplete=True)
        restored=Workbench(config_path=dest/'workbench/config.json')
        from optics_workbench.private_library import status
        self.assertFalse(status(restored)['restoration_complete'])
        self.assertEqual(status(restored)['missing_original_identities'],1)
        cfg=self.base/'runtime.json';private.write(cfg,{'servers':{'optics_workbench':{'env':{}}}})
        with self.assertRaises(ValueError):private.activate(dest,cfg,self.base/'codex')
        private.activate(dest,cfg,self.base/'codex',allow_incomplete=True)
    def test_activation_retry_preserves_meaningful_rollback(self):
        archive=self.make_backup();dest=self.base/'restored';private.restore(archive,dest)
        cfg=self.base/'runtime.json';old={'servers':{'optics_workbench':{'env':{'CUSTOM':'keep'}}}}
        private.write(cfg,old);private.activate(dest,cfg,self.base/'codex')
        previous=cfg.with_suffix('.previous.json').read_bytes()
        private.activate(dest,cfg,self.base/'codex')
        self.assertEqual(previous,cfg.with_suffix('.previous.json').read_bytes())
        self.assertEqual(private.read(cfg)['servers']['optics_workbench']['env']['CUSTOM'],'keep')

if __name__=='__main__':unittest.main()

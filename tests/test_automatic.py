"""Synthetic sources/transport, real ZIP and optional real restic verification."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import optics_private as private
import optics_incremental as inc
import optics_autobackup as auto
import optics_cloud as cloud
import cloud_tools
from test_quark import SyntheticClient
import test_cloud
import quark_transport as quark


class AutomaticRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.work=self.root/'work';self.work.mkdir();self.jobdir=self.work/'job';self.jobdir.mkdir()
        self.base=self.root/'baseline.zip';self.base.write_bytes(b'known baseline')
        private.write(self.base.with_suffix('.zip.sha256.json'),{'sha256':private.sha(self.base)})
        self.cfg=self.root/'automatic-backup.json'
        private.write(self.cfg,{'format':'optics-automatic-backup-v1','work_dir':str(self.work),
            'recovery':str(self.root/'recovery.json'),'baseline_archive':str(self.base),'seed_plan':str(self.root/'seed.json')})
        self.state=self.cfg.with_name('automatic-state.json')
        self.job={'directory':str(self.jobdir),'archive':str(self.jobdir/'optics.private.zip'),'phase':'upload','slot':auto.slot()}
        private.write(self.state,{'pending':self.job,'snapshot':'previous','archive':str(self.base)})
        self.load=patch.object(cloud,'load_ticket',return_value=(self.root/'recovery.json',{},None));self.load.start()
        self.clean=patch.object(auto,'cleanup_committed');self.cleanup=self.clean.start()
    def tearDown(self):self.clean.stop();self.load.stop();self.temp.cleanup()
    def test_transient_failure_retries_then_commits(self):
        with patch.object(auto,'checkpoint',side_effect=[quark.TransferError(1007),quark.TransferError(1007),{'snapshot':'new'}]) as run,patch.object(auto.time,'sleep') as sleep:
            result=auto.run(self.cfg,True,object())
        self.assertEqual(result['status'],'verified');self.assertEqual(run.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[30,120])
        self.assertEqual(private.read(self.state)['snapshot'],'new')
    def test_exhausted_retry_preserves_old_version_and_resumes(self):
        with patch.object(auto,'checkpoint',side_effect=quark.TransferError(1007)) as run,patch.object(auto.time,'sleep'):
            with self.assertRaises(quark.TransferError):auto.run(self.cfg,True,object())
        state=private.read(self.state);self.assertEqual(run.call_count,3)
        self.assertEqual(state['snapshot'],'previous');self.assertEqual(state['status'],'failed')
        self.assertEqual(state['pending']['phase'],'upload');self.assertFalse(auto.due(state))
        with patch.object(auto,'checkpoint',return_value={'snapshot':'new'}):auto.run(self.cfg,True,object())
        self.assertIsNone(private.read(self.state)['pending'])
    def test_authorization_failure_is_not_retried(self):
        with patch.object(auto,'checkpoint',side_effect=quark.TransferError(-1408)) as run,patch.object(auto.time,'sleep') as sleep:
            with self.assertRaises(quark.TransferError):auto.run(self.cfg,True,object())
        self.assertEqual(run.call_count,1);sleep.assert_not_called()
        self.assertEqual(private.read(self.state)['error'],'cloud_authorization_or_command')
        self.assertTrue(private.read(self.state)['needs_attention'])
        self.assertFalse(auto.due({**private.read(self.state),'retry_after':0}))
    def test_cleanup_failure_retries_maintenance_without_republishing(self):
        self.cleanup.side_effect=[OSError('synthetic disk failure'),None]
        with patch.object(auto,'checkpoint',return_value={'snapshot':'new'}) as run:
            with self.assertRaises(OSError):auto.run(self.cfg,True,object())
            self.assertEqual(private.read(self.state)['snapshot'],'new')
            self.assertEqual(auto.run(self.cfg,True,object())['status'],'maintenance_completed')
            self.assertEqual(run.call_count,1)
    def test_crash_after_zip_finalization_rebuilds_only_unpublished_assembly(self):
        self.job['phase']='scan';private.write(self.state,{'pending':self.job})
        archive=Path(self.job['archive']);archive.write_bytes(b'unpublished checkpoint')
        private.write(archive.with_suffix('.zip.sha256.json'),{'sha256':private.sha(archive)})
        def build(*args,**kwargs):
            self.assertFalse(archive.exists());self.assertEqual(self.base.read_bytes(),b'known baseline')
            return {'status':'created'}
        with patch.object(inc,'refresh_plan'),patch.object(inc,'build',side_effect=build),patch.object(auto,'checkpoint',return_value={'snapshot':'new'}):
            auto.run(self.cfg,True,object())
        self.assertTrue((self.jobdir/'assembly-retirement.jsonl').exists())


class RefreshPlanTests(unittest.TestCase):
    def test_explicit_imports_detect_new_files_and_exclude_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();imports=root/'imports';imports.mkdir()
            (imports/'new.txt').write_text('synthetic material')
            (imports/'password.txt').write_text('synthetic excluded')
            seed=root/'seed.json';private.write(seed,{'files':[],'missing':[],'workbench_config':{}})
            result=inc.refresh_plan(seed,root/'plan.json',[imports])
            self.assertEqual(len(result['files']),1)
            self.assertTrue(result['files'][0]['target'].endswith('/new.txt'))
    def test_changed_memory_artifact_keeps_missing_old_identity_and_current_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();artifact=root/'current_state.json';artifact.write_text('{"revision":2}')
            memory=root/'memory.sqlite3'
            with closing(sqlite3.connect(memory)) as db:
                db.execute('CREATE TABLE entries(payload TEXT)')
                db.execute('INSERT INTO entries VALUES (?)',(json.dumps({'artifacts':[{'path':str(artifact),'sha256':'0'*64}]}),));db.commit()
            seed=root/'seed.json';private.write(seed,{'files':[{'source':str(memory),'target':'workflow-memory/memory.sqlite3','aliases':[str(memory)],'bytes':memory.stat().st_size}], 'missing':[],'workbench_config':{}})
            result=inc.refresh_plan(seed,root/'plan.json')
            self.assertEqual(result['missing'][0]['sha256'],'0'*64)
            self.assertTrue(any(x['source']==str(artifact) and x['target'].startswith('evidence/current/') for x in result['files']))


class IncrementalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.source=self.root/'原文.txt';self.source.write_text('first 中文\n'*100,encoding='utf8')
        self.other=self.root/'notes.txt';self.other.write_text('unchanged\n'*100)
        self.db=self.root/'memory.sqlite3'
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE entries(id INTEGER)');db.execute('INSERT INTO entries VALUES (1)');db.commit()
        self.plan=self.root/'plan.json'
        self.data={'complete':True,'missing':[],'workbench_config':{},'files':[
            {'source':str(p),'target':target,'aliases':[str(p)],'expected_sha256':expected,'bytes':p.stat().st_size}
            for p,target,expected in [(self.source,'evidence/source.txt',private.sha(self.source)),(self.other,'notes.txt',None),(self.db,'workflow-memory/memory.sqlite3',None)]]}
        private.write(self.plan,self.data);self.base=self.root/'base.zip';private.backup(self.plan,self.base)
        self.cache=self.root/'source-cache.json'
    def tearDown(self):self.temp.cleanup()
    def test_unchanged_skips_archive_then_new_file_is_standalone_restorable(self):
        result=inc.build(self.plan,self.base,self.root/'none.zip',self.cache)
        self.assertEqual(result['status'],'unchanged');self.assertFalse((self.root/'none.zip').exists())
        os.replace(self.cache.with_suffix('.next.json'),self.cache)
        added=self.root/'新增.txt';added.write_text('new evidence 中文',encoding='utf8')
        self.data['files'].append({'source':str(added),'target':'new.txt','aliases':[str(added)],'expected_sha256':None,'bytes':added.stat().st_size})
        private.write(self.plan,self.data)
        output=self.root/'new.zip';result=inc.build(self.plan,self.base,output,self.cache)
        self.assertEqual(result['new_objects'],1);self.assertEqual(result['reused_objects'],3)
        with zipfile.ZipFile(output) as z:self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),len(set(z.namelist())))
        private.restore(output,self.root/'restored')
        self.assertEqual((self.root/'restored/new.txt').read_text(encoding='utf8'),'new evidence 中文')
        self.assertEqual(private.database_counts(self.root/'restored/workflow-memory/memory.sqlite3'),{'entries':1})
    def test_changed_historical_source_keeps_both_old_identity_and_new_bytes(self):
        old=self.source.read_bytes();self.source.write_text('revised original',encoding='utf8')
        output=self.root/'changed.zip';inc.build(self.plan,self.base,output,self.cache)
        private.restore(output,self.root/'restored')
        self.assertEqual((self.root/'restored/evidence/source.txt').read_bytes(),old)
        newest=next((self.root/'restored/evidence/updated').rglob('原文.txt'))
        self.assertEqual(newest.read_text(),'revised original')
    def test_missing_archived_source_is_retained_without_overwriting_current_data(self):
        self.source.unlink()
        result=inc.build(self.plan,self.base,self.root/'new.zip',self.cache)
        self.assertEqual(result['retained_missing_sources'],1);self.assertEqual(result['status'],'unchanged')
    def test_sqlite_change_is_snapshotted_and_previous_archive_is_unchanged(self):
        baseline=private.sha(self.base)
        with closing(sqlite3.connect(self.db)) as db:db.execute('INSERT INTO entries VALUES (2)');db.commit()
        output=self.root/'db.zip';result=inc.build(self.plan,self.base,output,self.cache)
        self.assertEqual(result['new_objects'],1);self.assertEqual(private.sha(self.base),baseline)
        private.restore(output,self.root/'restored')
        self.assertEqual(private.database_counts(self.root/'restored/workflow-memory/memory.sqlite3'),{'entries':2})
    def test_full_audit_does_not_trust_matching_cached_stamp(self):
        private.write(self.cache,{str(self.other):{'stamp':inc.stamp(self.other),'sha256':'0'*64}})
        result=inc.build(self.plan,self.base,self.root/'audit.zip',self.cache,full_hash=True)
        self.assertEqual(result['status'],'unchanged')
    def test_credentials_and_unsafe_targets_are_rejected(self):
        secret=self.root/'password.key';secret.write_text('synthetic')
        self.data['files'].append({'source':str(secret),'target':'secret.txt','aliases':[],'bytes':9})
        private.write(self.plan,self.data)
        with self.assertRaises(ValueError):inc.build(self.plan,self.base,self.root/'bad.zip',self.cache)
        self.data['files'].pop();self.data['files'][0]['target']='../escape';private.write(self.plan,self.data)
        with self.assertRaises(ValueError):inc.build(self.plan,self.base,self.root/'bad.zip',self.cache)
    def test_corrupted_baseline_and_existing_output_refuse_overwrite(self):
        self.base.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):inc.build(self.plan,self.base,self.root/'bad.zip',self.cache)
    def test_scheduler_catchup_and_retry_wait(self):
        now=datetime(2026,11,16,1,0,tzinfo=timezone.utc)
        self.assertFalse(auto.due({'last_success_slot':'2026-11-15T02:00:00+00:00'},now))
        self.assertTrue(auto.due({'last_success_slot':'2026-11-14T02:00:00+00:00'},now))
        self.assertFalse(auto.due({'pending':{'phase':'upload'},'retry_after':10**12},now))
    def test_exclusive_lock_releases_after_error(self):
        lock=self.root/'lock'
        with auto.exclusive(lock):
            with self.assertRaises(RuntimeError):
                with auto.exclusive(lock):pass
        with auto.exclusive(lock):pass
    def test_zip64_offsets_survive_raw_reuse_in_both_directions(self):
        with patch.object(zipfile,'ZIP64_LIMIT',128):
            old=self.root/'offset-old.zip'
            with zipfile.ZipFile(old,'w',allowZip64=True) as z:
                z.writestr('padding',b'x'*512);z.writestr('objects/test',b'payload'*40)
            for prefix in [False,True]:
                output=self.root/('offset-'+str(prefix)+'.zip')
                with zipfile.ZipFile(old) as src,zipfile.ZipFile(output,'w',allowZip64=True) as dst:
                    if prefix:dst.writestr('long-padding',b'y'*1024)
                    inc.copy_compressed(src,dst,'objects/test')
                with zipfile.ZipFile(output) as z:
                    self.assertEqual(z.read('objects/test'),b'payload'*40);self.assertIsNone(z.testzip())


@unittest.skipUnless(os.environ.get('OPTICS_CLOUD_INTEGRATION')=='1','Real restic test opt-in')
class IncrementalCloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tools=cloud_tools.ensure_tools()
    setUp=test_cloud.CloudIntegrationTests.setUp
    tearDown=test_cloud.CloudIntegrationTests.tearDown
    def test_cloud_delta_readback_failure_retry_history_and_old_version_restore(self):
        import quark_transport as q
        client=SyntheticClient(self.root/'synthetic-cloud')
        q.publish(self.ticket,client,self.tools);q.verify(self.ticket,self.root/'base-readback',client,self.tools)
        original=private.read(self.ticket);reads=client.reads;uploads=client.uploads
        db=self.root/'memory.sqlite3'
        with closing(sqlite3.connect(db)) as con:con.execute('INSERT INTO entries VALUES (?,?)',('second','second revision'));con.commit()
        output=self.root/'next.zip';inc.build(self.root/'plan.json',self.archive,output,self.root/'cache.json')
        client.tamper=True
        with self.assertRaises(ValueError):auto.checkpoint(self.ticket,output,self.root/'delta-readback',client,self.tools)
        self.assertEqual(private.read(self.ticket),original)
        client.tamper=False
        result=auto.checkpoint(self.ticket,output,self.root/'delta-readback',client,self.tools)
        self.assertGreater(result['new_objects'],0);self.assertGreater(result['reused_cloud_objects'],0)
        self.assertEqual(client.uploads-uploads,result['new_objects'])
        self.assertLess(client.reads-reads,2*len(private.read(self.ticket)['quark']['objects']))
        self.assertEqual(private.read(self.ticket.parent/'previous-recovery.json')['snapshot'],original['snapshot'])
        old=self.ticket.parent/('recovery-'+original['snapshot']+'.json')
        cloud.recover(old,self.root/'old-restored',self.root/'old-download',install=False,tools=self.tools,quark_client=client)
        self.assertEqual(private.database_counts(self.root/'old-restored/workflow-memory/memory.sqlite3'),{'entries':1})
        cloud.recover(self.ticket,self.root/'new-restored',self.root/'new-download',install=False,tools=self.tools,quark_client=client)
        self.assertEqual(private.database_counts(self.root/'new-restored/workflow-memory/memory.sqlite3'),{'entries':2})
        repeated=auto.checkpoint(self.ticket,output,self.root/'delta-readback',client,self.tools)
        self.assertTrue(repeated['already_verified'])

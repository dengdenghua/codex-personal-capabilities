"""Synthetic Quark CLI protocol tests; these are NOT live cloud acceptance."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import optics_cloud as cloud
import optics_private as private
import quark_transport as quark
import test_cloud


class SyntheticClient:
    def prepare(self):pass
    def __init__(self,remote):self.remote=remote;remote.mkdir();self.uploads=0;self.reads=0;self.fail=False;self.tamper=False
    def run(self,args,runtime,on_record=None):
        runtime=Path(runtime);runtime.mkdir(parents=True,exist_ok=True)
        records=[]
        if args[0]=='upload':
            sources=[]
            for value in args[1:]:
                source=Path(value);sources.extend(p for p in source.rglob('*') if p.is_file()) if source.is_dir() else sources.append(source)
            for source in sources:
                fid='synthetic-'+private.sha(source);shutil.copyfile(source,self.remote/fid);self.uploads+=1
                item={'type':'list','code':0,'data':{'fileId':fid,'fileName':source.name,'fileSize':source.stat().st_size}}
                records.append(item)
                if on_record:on_record(item)
                if self.fail:raise RuntimeError('Synthetic interrupted transfer')
        elif args[0]=='read-file':
            for fid in args[1:]:
                target=runtime/fid;shutil.copyfile(self.remote/fid,target);self.reads+=1
                if self.tamper:target.write_bytes(b'tampered')
                item={'type':'list','code':0,'data':{'fid':fid,'filePath':str(target),'fileSize':target.stat().st_size}}
                records.append(item)
                if on_record:on_record(item)
        else:raise AssertionError(args)
        return {'type':'result','code':0,'data':{}},records

    def read(self,obj,runtime,receive):self.run(['read-file',obj['fid']],runtime,receive)


class QuarkBoundaryTests(unittest.TestCase):
    def test_cli_idle_timeout_uses_bounded_read_retry(self):
        client=object.__new__(quark.Client)
        client._read_once=Mock(side_effect=[quark.TransferIdleTimeout(),'verified'])
        with patch.object(quark.time,'sleep'):
            self.assertEqual(client.read({'fid':'synthetic'},Path('synthetic'),None),'verified')
        self.assertEqual(client._read_once.call_count,2)
        client._read_once=Mock(side_effect=quark.TransferIdleTimeout())
        with patch.object(quark.time,'sleep'),self.assertRaises(quark.TransferIdleTimeout):
            client.read({'fid':'synthetic'},Path('synthetic'),None)
        self.assertEqual(client._read_once.call_count,3)
    def test_read_worker_bounds_are_checked_before_setup(self):
        for count in [0,65,-1,True]:
            with self.assertRaises(ValueError):quark.Client(workers=count)
    def test_network_read_retry_delivers_once(self):
        client=object.__new__(quark.Client)
        client._read_once=Mock(side_effect=[quark.TransferError(-100,'Request timeout after 60000ms: POST [redacted]'),quark.TransferError(1007),'verified'])
        with patch.object(quark.time,'sleep'):
            self.assertEqual(client.read({'fid':'synthetic'},Path('synthetic'),None),'verified')
        self.assertEqual(client._read_once.call_count,3)

    def test_authorization_failure_is_not_blindly_retried(self):
        for error in [quark.TransferError(-1408),quark.TransferError(-100,"unknown command 'read-file'")]:
            client=object.__new__(quark.Client);client._read_once=Mock(side_effect=error)
            with self.assertRaises(quark.TransferError):client.read({'fid':'synthetic'},Path('synthetic'),None)
            self.assertEqual(client._read_once.call_count,1)

    def test_retrieval_uses_actual_cli_capabilities(self):
        self.assertEqual(quark.download_mode('Commands:\n  download [options]  Retrieve files'),'download')
        self.assertEqual(quark.download_mode('Commands:\n  read-file [options] [fids...] Retrieve'),'read-file')

    def test_missing_retrieval_capability_fails_before_transfer(self):
        with self.assertRaises(ValueError):quark.download_mode('Commands:\n  upload [options]')

    def test_paths_reject_secret_traversal_and_platform_escapes(self):
        for path in ['password.key','../config','data/../config','/config','C:/config','keys/password.key','data\\xx','locks/'+'a'*64,'data/ab/'+'c'*64]:
            with self.subTest(path=path),self.assertRaises(ValueError):quark.safe_relative(path)
        self.assertEqual(str(quark.safe_relative('data/ab/'+'ab'+'c'*62)),'data/ab/'+'ab'+'c'*62)

    def test_inventory_rejects_plaintext(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'password.key').write_text('synthetic')
            with self.assertRaises(ValueError):quark.inventory(root)

    def test_readback_receipts_are_excluded_from_retained_mirror_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'config').write_bytes(b'opaque')
            for name in ['keys','snapshots']:
                (root/name).mkdir();(root/name/('a'*64 if name=='keys' else 'b'*64)).write_bytes(b'opaque')
            for name in ['.quark-cache.json','.quark-readback-progress.json']:
                (root/name).write_text('{}')
            self.assertEqual(len(quark.inventory(root)),3)
            (root/'data').mkdir();(root/'data/.quark-cache.json').write_text('{}')
            with self.assertRaises(ValueError):quark.inventory(root)


@unittest.skipUnless(os.environ.get('OPTICS_CLOUD_INTEGRATION')=='1','Real restic with synthetic Quark transport')
class QuarkProtocolTests(unittest.TestCase):
    setUpClass=classmethod(lambda cls:setattr(cls,'tools',cloud.cloud_tools.ensure_tools()))
    setUp=test_cloud.CloudIntegrationTests.setUp
    tearDown=test_cloud.CloudIntegrationTests.tearDown

    def test_unfinished_readback_can_resume_without_refetching_verified_objects(self):
        client=SyntheticClient(self.root/'synthetic-cloud');client.workers=4
        quark.publish(self.ticket,client,self.tools)
        quark.materialize(self.ticket,self.root/'readback',client)
        count=client.reads
        quark.verify(self.ticket,self.root/'readback',client,self.tools,resume=True)
        self.assertEqual(client.reads,count)
        progress=private.read(self.root/'readback/.quark-readback-progress.json')
        self.assertEqual(progress['verified_objects'],progress['objects'])
        with self.assertRaises(ValueError):quark.verify(self.ticket,self.root/'readback',client,self.tools,resume=True)

    def test_roundtrip_real_crypto_and_sqlite_using_synthetic_transport(self):
        client=SyntheticClient(self.root/'synthetic-cloud')
        result=quark.publish(self.ticket,client,self.tools)
        self.assertEqual(result['status'],'quark_uploaded_pending_readback')
        self.assertEqual(private.read(self.ticket)['storage'],'local-encrypted')
        quark.verify(self.ticket,self.root/'readback',client,self.tools)
        self.assertEqual(private.read(self.ticket)['storage'],'quark')
        # New machine has no access to the old mirror, only offline key + locator.
        shutil.rmtree(self.root/'ciphertext')
        cloud.recover(self.ticket,self.root/'restored',install=False,tools=self.tools,quark_client=client)
        self.assertEqual(private.database_counts(self.root/'restored/workflow-memory/memory.sqlite3'),{'entries':1})

    def test_interruption_reuses_only_recorded_successful_objects(self):
        client=SyntheticClient(self.root/'synthetic-cloud');client.fail=True
        with self.assertRaises(RuntimeError):quark.publish(self.ticket,client,self.tools)
        saved=private.read(self.ticket)['quark'];self.assertEqual(sum(bool(o.get('fid')) for o in saved['objects']),1)
        client.fail=False;quark.publish(self.ticket,client,self.tools)
        self.assertEqual(client.uploads,len(saved['objects']))
        quark.materialize(self.ticket,self.root/'readback',client)
        count=client.reads;quark.materialize(self.ticket,self.root/'readback',client)
        self.assertEqual(client.reads,count)

    def test_transient_network_retry_does_not_resend_confirmed_objects(self):
        client=SyntheticClient(self.root/'synthetic-cloud');original=client.run;first=[True]
        def run(args,runtime,on_record=None):
            if first[0]:
                first[0]=False;original(args[:2],runtime,on_record);raise quark.TransferError(1007)
            return original(args,runtime,on_record)
        client.run=run
        with patch.object(quark.time,'sleep'):quark.publish(self.ticket,client,self.tools)
        self.assertEqual(client.uploads,len(private.read(self.ticket)['quark']['objects']))

    def test_cloud_corruption_does_not_publish_verified_record(self):
        client=SyntheticClient(self.root/'synthetic-cloud');quark.publish(self.ticket,client,self.tools);client.tamper=True
        with self.assertRaises(ValueError):quark.verify(self.ticket,self.root/'readback',client,self.tools)
        self.assertFalse(private.read(self.ticket)['quark']['verified'])

    def test_explicit_verification_reads_cloud_again_even_with_valid_cache(self):
        client=SyntheticClient(self.root/'synthetic-cloud');quark.publish(self.ticket,client,self.tools)
        quark.verify(self.ticket,self.root/'readback',client,self.tools)
        count=client.reads
        quark.verify(self.ticket,self.root/'readback',client,self.tools)
        self.assertEqual(client.reads,count*2)
        self.assertEqual(private.read(self.ticket)['quark']['local_repository'],str(self.root/'ciphertext'))

    def test_backup_failure_preserves_current_cloud_locator(self):
        client=SyntheticClient(self.root/'synthetic-cloud');quark.publish(self.ticket,client,self.tools)
        quark.verify(self.ticket,self.root/'readback',client,self.tools)
        before=private.read(self.ticket);client.tamper=True
        with self.assertRaises(ValueError):quark.backup(self.ticket,self.archive,self.root/'next-readback',client,self.tools)
        self.assertEqual(private.read(self.ticket),before)

    def test_next_snapshot_reuses_immutable_cloud_objects(self):
        client=SyntheticClient(self.root/'synthetic-cloud');quark.publish(self.ticket,client,self.tools)
        quark.verify(self.ticket,self.root/'readback',client,self.tools)
        before=private.read(self.ticket)
        source=self.root/'synthetic.txt';source.write_text('Changed synthetic optical evidence',encoding='utf8')
        plan=self.root/'plan.json';record=private.read(plan)
        record['files'][0].update(expected_sha256=private.sha(source),bytes=source.stat().st_size)
        private.write(plan,record)
        archive=self.root/'next.private.zip';private.backup(plan,archive)
        quark.backup(self.ticket,archive,self.root/'next-readback',client,self.tools)
        after=private.read(self.ticket)
        self.assertNotEqual(after['snapshot'],before['snapshot'])
        self.assertEqual(client.uploads,len(after['quark']['objects']))
        self.assertEqual(private.read(self.ticket.with_name('previous-recovery.json')),before)

    def test_download_cannot_follow_a_hardlink_or_unrelated_directory(self):
        client=SyntheticClient(self.root/'synthetic-cloud');quark.publish(self.ticket,client,self.tools)
        readback=self.root/'readback';quark.materialize(self.ticket,readback,client)
        target=readback/'config';target.unlink();protected=self.root/'user-file';protected.write_text('keep')
        os.link(protected,target)
        with self.assertRaises(ValueError):quark.materialize(self.ticket,readback,client)
        self.assertEqual(protected.read_text(),'keep')
        with self.assertRaises(ValueError):quark.materialize(self.ticket,self.root/'ciphertext',client)


if __name__=='__main__':unittest.main()

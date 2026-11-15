from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import optics_cloud as cloud
import optics_private as private
import cloud_tools


class CloudBoundaryTests(unittest.TestCase):
    def test_public_git_location_rejected_for_keys(self):
        with self.assertRaises(ValueError):cloud.local_only(ROOT/'recovery.json')

    def test_known_sync_folder_rejected_for_keys(self):
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,{'OneDrive':temporary}):
            with self.assertRaises(ValueError):cloud.local_only(Path(temporary)/'password.key')

    def test_remote_must_be_dedicated_and_not_github(self):
        for value in ['cloud:','cloud:/','cloud:../other','https://github.com/example','cloud:folder\nother']:
            with self.subTest(value=value),self.assertRaises(ValueError):cloud.validate_remote(value)
        self.assertEqual(cloud.validate_remote('private:OpticsVault'),'private:OpticsVault')

    def test_missing_unlock_key_is_not_regenerated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();record=root/'recovery.json'
            private.write(record,{'format':cloud.FORMAT,'key_file':'password.key'})
            with self.assertRaises(ValueError):cloud.load_ticket(record)
            self.assertFalse((root/'password.key').exists())

    def test_untrusted_snapshot_or_transport_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();key=root/'password.key';key.write_text('synthetic-test-key-'*4)
            record=root/'recovery.json'
            private.write(record,{'format':cloud.FORMAT,'key_file':'password.key','storage':'cloud','repository':'sftp:some-host:some-path'})
            with self.assertRaises(ValueError):cloud.load_ticket(record)
            private.write(record,{'format':cloud.FORMAT,'key_file':'password.key','storage':'cloud','repository':'rclone:private:folder','snapshot':'--other-option','archive_sha256':'0'*64})
            with self.assertRaises(ValueError):cloud.load_ticket(record)

    def test_private_recovery_record_rejected_by_public_scanner(self):
        import validate
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();private.write(root/'renamed.json',{'format':cloud.FORMAT})
            self.assertTrue(any('private optical manifest' in error for error in validate.problems(root)))


@unittest.skipUnless(os.environ.get('OPTICS_CLOUD_INTEGRATION')=='1','Set OPTICS_CLOUD_INTEGRATION=1 for real pinned restic/rclone acceptance')
class CloudIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools=cloud_tools.ensure_tools()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='optics-cloud-test-');self.root=Path(self.temp.name).resolve()
        source=self.root/'synthetic.txt';source.write_text('Synthetic optical evidence: 合成数据\n'*100,encoding='utf8')
        dbfile=self.root/'memory.sqlite3'
        with closing(sqlite3.connect(dbfile)) as db:
            db.execute('CREATE TABLE entries(id TEXT, text TEXT)');db.execute('INSERT INTO entries VALUES (?,?)',('synthetic','中文合成记忆'));db.commit()
        plan=self.root/'plan.json'
        private.write(plan,{'complete':True,'missing':[],'workbench_config':{},'files':[
            {'source':str(source),'target':'evidence/synthetic.txt','aliases':[str(source)],'expected_sha256':private.sha(source),'bytes':source.stat().st_size},
            {'source':str(dbfile),'target':'workflow-memory/memory.sqlite3','aliases':[str(dbfile)],'expected_sha256':None,'bytes':dbfile.stat().st_size}]})
        self.archive=self.root/'optics.private.zip';private.backup(plan,self.archive)
        self.ticket=cloud.initialize(self.root/'offline-key',self.root/'ciphertext',self.tools)
        self.vault=cloud.Vault(self.ticket,self.tools);self.vault.backup(self.archive)

    def tearDown(self):self.temp.cleanup()

    @unittest.skipUnless(os.name=='nt','Windows NTFS compression')
    def test_compressed_restore_keeps_sqlite_and_hashes_valid(self):
        destination=self.root/'compressed-recovery'
        result=cloud.recover(self.ticket,destination,install=False,tools=self.tools,ntfs_compressed=True)
        self.assertEqual(result['status'],'restored')
        self.assertTrue(private.read(destination/'restore-report.json')['ntfs_compressed'])
        private.verify_restored(self.archive,destination)
        self.assertEqual(private.database_counts(destination/'workflow-memory/memory.sqlite3'),{'entries':1})

    def test_real_encrypted_sqlite_restore_and_retry(self):
        before=(self.ticket.parent/'password.key').read_bytes()
        self.assertEqual(cloud.initialize(self.ticket.parent,self.root/'ciphertext',self.tools),self.ticket)
        self.assertEqual((self.ticket.parent/'password.key').read_bytes(),before)
        destination=self.root/'recovered'
        result=cloud.recover(self.ticket,destination,install=False,tools=self.tools)
        self.assertEqual(result['status'],'restored')
        self.assertEqual(private.database_counts(destination/'workflow-memory/memory.sqlite3'),{'entries':1})
        cloud.recover(self.ticket,destination,install=False,tools=self.tools)
        (destination/'evidence/synthetic.txt').write_text('user changed it')
        with self.assertRaises(ValueError):cloud.recover(self.ticket,destination,install=False,tools=self.tools)

    def test_wrong_key_cannot_decrypt_and_key_is_absent_from_ciphertext(self):
        key=self.ticket.parent/'password.key';secret=key.read_bytes().strip()
        for path in (self.root/'ciphertext').rglob('*'):
            if path.is_file():self.assertNotIn(secret,path.read_bytes())
        key.write_text('different synthetic invalid recovery key'*2)
        with self.assertRaises((ValueError,RuntimeError)):cloud.Vault(self.ticket,self.tools).verify()

    def test_tampered_encrypted_pack_fails_authenticated_readback(self):
        pack=next(p for p in (self.root/'ciphertext/data').rglob('*') if p.is_file())
        # Restic deliberately makes Linux packs read-only. This synthetic fault
        # injection must first make its own temporary object writable.
        pack.chmod(0o600)
        content=bytearray(pack.read_bytes());content[len(content)//2]^=1;pack.write_bytes(content)
        with self.assertRaises((ValueError,RuntimeError)):self.vault.verify()

    def test_interrupted_download_is_repaired_before_restore(self):
        cache=self.root/'download';stage=cache/('.download-'+self.vault.ticket['snapshot']);stage.mkdir(parents=True)
        (stage/self.archive.name).write_bytes(b'partial interrupted transfer')
        downloaded=self.vault.download(cache)
        self.assertEqual(private.sha(downloaded),private.sha(self.archive))

    def test_download_never_overwrites_a_hardlinked_file(self):
        cache=self.root/'download';stage=cache/('.download-'+self.vault.ticket['snapshot']);stage.mkdir(parents=True)
        protected=self.root/'protected-user-file';protected.write_bytes(b'keep original bytes')
        os.link(protected,stage/self.archive.name)
        with self.assertRaises(ValueError):self.vault.download(cache)
        self.assertEqual(protected.read_bytes(),b'keep original bytes')

    def test_real_rclone_transport_does_not_claim_public_cloud(self):
        config=self.root/'rclone.conf';config.write_text('[fixture]\ntype = local\n',encoding='utf8')
        remote='fixture:'+(self.root/'remote-ciphertext').as_posix()
        with self.assertRaises(ValueError):cloud.publish(self.ticket,remote,config,self.tools)
        result=cloud.publish(self.ticket,remote,config,self.tools,allow_local_test=True)
        self.assertEqual(result['status'],'transport_test_verified')
        self.assertEqual(private.read(self.ticket)['storage'],'transport-test')
        self.assertFalse((self.root/'remote-ciphertext/password.key').exists())
        cloud.recover(self.ticket,self.root/'remote-recovered',rclone_config=config,install=False,tools=self.tools)

    def test_unrelated_files_block_upload(self):
        (self.root/'ciphertext/password.key').write_text('synthetic do not upload')
        with self.assertRaises(ValueError):cloud.publish(self.ticket,'fixture:folder',tools=self.tools,allow_local_test=True)


if __name__=='__main__':unittest.main()

"""Encrypted optical checkpoints. Only ciphertext is eligible for cloud upload.

Restic owns encryption/authentication and snapshot storage; rclone owns transport.
The offline unlock secret and cloud credentials are never included in backup inputs.
"""
import argparse
from collections import deque
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import cloud_tools
import optics_private as private

FORMAT='optics-cloud-recovery-v1'
ROOT=Path(__file__).resolve().parents[1]


def local_only(path):
    path=private.outside(path)
    roots=[os.environ.get(name) for name in ['OneDrive','OneDriveConsumer','OneDriveCommercial','Dropbox']]
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\OneDrive\Accounts') as accounts:
                for index in range(winreg.QueryInfoKey(accounts)[0]):
                    with winreg.OpenKey(accounts,winreg.EnumKey(accounts,index)) as account:
                        try:roots.append(winreg.QueryValueEx(account,'UserFolder')[0])
                        except OSError:pass
        except OSError:pass
    for value in roots:
        if value and path.is_relative_to(Path(value).expanduser().resolve()):
            raise ValueError('Recovery secrets must be outside cloud-synchronized folders')
    return path


def secure_directory(path):
    path=local_only(path);path.mkdir(parents=True,exist_ok=False)
    if os.name=='nt':
        raw=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True)
        sid=list(csv.reader(raw.splitlines()))[0][-1]
        if not re.fullmatch(r'S-1-[0-9-]+',sid):raise ValueError('Could not determine local user identity')
        result=subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],capture_output=True)
        if result.returncode:raise ValueError('Could not restrict recovery folder access; no key was written')
    else:path.chmod(0o700)
    return path


def save_ticket(path,ticket):
    path=local_only(path)
    temporary=path.with_suffix('.pending.json')
    private.write(temporary,ticket)
    if os.name!='nt':temporary.chmod(0o600)
    os.replace(temporary,path)


def load_ticket(path):
    path=local_only(path);ticket=private.read(path)
    if ticket.get('format')!=FORMAT:raise ValueError('Not an optical cloud recovery file')
    if ticket.get('key_file')!='password.key':raise ValueError('Unexpected recovery key location')
    key=local_only(path.parent/'password.key')
    if not key.is_file() or key.stat().st_size<32:raise ValueError('Local recovery key is missing; it is never downloaded from the cloud')
    repository=ticket['repository']
    if ticket.get('storage')=='quark':
        import quark_transport
        if repository!='quark:offline-object-inventory' or not ticket.get('quark',{}).get('verified'):
            raise ValueError('Quark backup has not completed authenticated cloud readback')
        quark_transport.validate_objects(ticket['quark']['objects'])
    elif ticket.get('storage') in {'cloud','transport-test'}:
        if not repository.startswith('rclone:'):raise ValueError('Cloud recovery only accepts the configured rclone transport')
        validate_remote(repository.removeprefix('rclone:'))
    elif ticket.get('storage')=='local-encrypted':
        if not Path(repository).is_absolute():raise ValueError('Local encrypted repository must be an absolute local path')
        ticket['repository']=str(private.outside(repository))
    else:raise ValueError('Unknown encrypted storage mode')
    if 'snapshot' in ticket:
        if not re.fullmatch('[0-9a-f]{64}',ticket['snapshot']) or not re.fullmatch('[0-9a-f]{64}',ticket['archive_sha256']):
            raise ValueError('Invalid encrypted snapshot identity')
        name=ticket['archive_name'];member=PurePosixPath(ticket['archive_path'])
        if not name or name in {'.','..'} or '/' in name or '\\' in name or ':' in name or member.name!=name or not member.is_absolute() or '..' in member.parts:
            raise ValueError('Unsafe archive location in recovery record')
        if any(not isinstance(ticket[k],int) or ticket[k]<0 for k in ['archive_bytes','restore_bytes','missing_originals']):
            raise ValueError('Invalid recovery sizes')
    return path,ticket,key


def validate_remote(remote):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]*:[^\r\n\x00]+',remote):
        raise ValueError('Use a configured rclone remote and a dedicated private folder: remote:folder')
    prefix=remote.split(':',1)[1].strip('/')
    if not prefix or '..' in prefix.replace('\\','/').split('/') or 'github.com' in remote.lower():
        raise ValueError('Use a dedicated private cloud folder, never a Git repository or account root')
    return remote


def reject_link(path):
    if path.exists() or path.is_symlink():
        state=path.lstat()
        if path.is_symlink() or getattr(state,'st_file_attributes',0)&0x400 or (path.is_file() and state.st_nlink>1):
            raise ValueError('Links, junctions and shared hardlinks are not allowed in transfer staging')


class Vault:
    def __init__(self,ticket_path,tools=None,rclone_config=None,repository=None):
        self.path,self.ticket,self.key=load_ticket(ticket_path)
        if self.ticket['storage']=='quark' and not repository:
            raise ValueError('Quark requires ciphertext retrieval before opening the encrypted vault')
        self.tools=tools or cloud_tools.ensure_tools()
        self.repository=repository or self.ticket['repository']
        self.env={k:v for k,v in os.environ.items() if not k.startswith('RESTIC_')}
        self.env.update(RESTIC_PASSWORD_FILE=str(self.key),GOMAXPROCS='2',RESTIC_PROGRESS_FPS='0.05')
        if rclone_config:self.env['RCLONE_CONFIG']=str(local_only(rclone_config))
        self.env['PATH']=str(Path(self.tools['rclone']).parent)+os.pathsep+self.env.get('PATH','')

    def command(self,args):
        return [self.tools['restic'],'--repo',self.repository,'--password-file',str(self.key),
                '--cache-dir',str(self.path.parent/'cache'),'--compression','off',*args]

    @staticmethod
    def failure(code):
        if code==12:return ValueError('The local recovery key does not unlock this vault')
        return RuntimeError('Encrypted backup command failed (exit '+str(code)+'); check cloud login, network and vault availability. No secret or raw server output is printed.')

    def json(self,args):
        result=subprocess.run(self.command(['--json',*args]),env=self.env,capture_output=True,text=True,encoding='utf8')
        if result.returncode:raise self.failure(result.returncode)
        return json.loads(result.stdout)

    def check_identity(self):
        config=self.json(['cat','config'])
        if config['id']!=self.ticket['repository_id']:raise ValueError('This is a different encrypted vault; stopped')
        return config

    def stream(self,args,output=None,expected=None,cwd=None):
        """Bounded binary streaming. Never accept plaintext before process success/hash verification."""
        digest=hashlib.sha256();size=0
        with tempfile.TemporaryFile() as errors:
            child=subprocess.Popen(self.command(args),cwd=cwd,env=self.env,stdout=subprocess.PIPE,stderr=errors)
            try:
                for chunk in iter(lambda:child.stdout.read(1024*1024),b''):
                    digest.update(chunk);size+=len(chunk)
                    if output:output.write(chunk)
                code=child.wait()
                if code:raise self.failure(code)
            finally:
                child.stdout.close()
                if child.poll() is None:child.terminate();child.wait(timeout=10)
        actual=digest.hexdigest()
        if expected and actual!=expected:raise ValueError('Decrypted archive SHA256 does not match the offline recovery record')
        return {'sha256':actual,'bytes':size}

    def backup(self,archive):
        archive=private.outside(archive)
        checksum=archive.with_suffix(archive.suffix+'.sha256.json')
        expected=private.read(checksum)['sha256']
        if private.sha(archive)!=expected:raise ValueError('Private archive checksum mismatch; nothing uploaded')
        with zipfile.ZipFile(archive) as data:
            manifest=json.loads(data.read('manifest.json'))
        if manifest.get('format')!='optics-private-backup-v1':raise ValueError('Only optical private archives may be backed up')
        for item in manifest['files']:
            if PurePosixPath(item['target']).name.lower() in {'password.key','recovery.json','rclone.conf','auth.json','credentials.json'}:
                raise ValueError('Unlock/account material is forbidden in cloud backup inputs')
        self.check_identity()
        summary=None
        with tempfile.TemporaryFile() as errors:
            child=subprocess.Popen(self.command(['--json','backup','--host','optics-vault','--tag','optics-private-v1','--',archive.name,checksum.name]),
                                   cwd=archive.parent,env=self.env,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf8')
            try:
                for line in child.stdout:
                    item=json.loads(line)
                    if item.get('message_type')=='summary':summary=item
                    elif item.get('message_type')=='status':print('Encrypted backup progress:',item.get('bytes_done',0),'bytes',flush=True)
                code=child.wait()
                if code:raise self.failure(code)
            finally:
                child.stdout.close()
                if child.poll() is None:child.terminate();child.wait(timeout=10)
        if not summary or not re.fullmatch('[0-9a-f]{8,64}',summary.get('snapshot_id','')):raise ValueError('No committed encrypted snapshot returned')
        snapshot=summary['snapshot_id']
        nodes=self.nodes(snapshot)
        candidates=[n['path'] for n in nodes if n.get('type')=='file' and n.get('name')==archive.name]
        if len(candidates)!=1:raise ValueError('Archive identity within snapshot is ambiguous')
        record={'snapshot':snapshot,'archive_name':archive.name,'archive_path':candidates[0],
                'archive_sha256':expected,'archive_bytes':archive.stat().st_size,
                'restore_bytes':sum(x['bytes'] for x in manifest['files']),
                'complete':manifest['complete'],'missing_originals':len(manifest['missing'])}
        # Commit recovery metadata only after a full authenticated readback.
        self.stream(['dump',snapshot,record['archive_path']],expected=expected)
        self.ticket.update(record);save_ticket(self.path,self.ticket)
        return {'status':'verified','storage':self.ticket['storage'],'snapshot':snapshot,'archive_bytes':record['archive_bytes'],'missing_originals':record['missing_originals']}

    def nodes(self,snapshot):
        result=subprocess.run(self.command(['--json','ls',snapshot]),env=self.env,capture_output=True,text=True,encoding='utf8')
        if result.returncode:raise self.failure(result.returncode)
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def verify(self):
        self.check_identity()
        # Verify every encrypted pack, including sidecars and repository objects
        # that the selected archive alone would not touch. Do not let a warm
        # metadata cache hide on-disk corruption.
        checked=subprocess.run(self.command(['--no-cache','check','--read-data']),env=self.env,capture_output=True)
        if checked.returncode:raise self.failure(checked.returncode)
        record=self.ticket
        result=self.stream(['dump',record['snapshot'],record['archive_path']],expected=record['archive_sha256'])
        if result['bytes']!=record['archive_bytes']:raise ValueError('Archive length mismatch')
        return {'status':'verified','storage':record['storage'],'snapshot':record['snapshot'],**result}

    def download(self,cache_dir):
        self.check_identity();cache=local_only(cache_dir);cache.mkdir(parents=True,exist_ok=True)
        name=self.ticket['archive_name']
        if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe archive name in recovery record')
        target=cache/name
        reject_link(target)
        if target.exists():
            if private.sha(target)!=self.ticket['archive_sha256']:raise ValueError('Existing local archive differs; choose a new cache directory')
            return target
        stage=cache/('.download-'+self.ticket['snapshot'])
        reject_link(stage);stage.mkdir(exist_ok=True)
        partial=stage/name
        reject_link(partial)
        allocated=partial.stat().st_size if partial.exists() else 0
        if shutil.disk_usage(cache).free<max(0,self.ticket['archive_bytes']-allocated)+256*1024*1024:
            raise OSError('Insufficient disk space for downloaded private archive')
        subtree=str(PurePosixPath(self.ticket['archive_path']).parent)
        # Restic repairs/reuses interrupted downloads in this snapshot-specific stage.
        command=['--json','restore',self.ticket['snapshot']+':'+subtree,'--target',str(stage),'--include','/'+name,'--verify']
        result=subprocess.run(self.command(command),env=self.env,capture_output=True)
        if result.returncode:raise self.failure(result.returncode)
        if not partial.is_file() or partial.stat().st_size!=self.ticket['archive_bytes'] or private.sha(partial)!=self.ticket['archive_sha256']:
            raise ValueError('Downloaded archive identity mismatch')
        os.replace(partial,target)
        private.write(target.with_suffix(target.suffix+'.sha256.json'),{'archive':name,'sha256':self.ticket['archive_sha256']})
        return target


def initialize(key_dir,local_repository,tools=None):
    repository=private.outside(local_repository)
    key_dir=local_only(key_dir)
    if key_dir.is_relative_to(repository) or repository.is_relative_to(key_dir):raise ValueError('Unlock keys and encrypted repository must be separate')
    existing=key_dir/'recovery.json'
    if existing.exists():
        vault=Vault(existing,tools)
        if vault.ticket['storage']!='local-encrypted' or Path(vault.repository)!=repository:
            raise ValueError('Existing recovery material belongs to a different vault')
        if not repository.exists():
            if vault.ticket.get('repository_id'):raise ValueError('Previously initialized vault is missing; do not replace its recovery key')
            vault.json(['init','--repository-version','2'])
        identity=vault.json(['cat','config'])['id']
        if vault.ticket.get('repository_id',identity)!=identity:raise ValueError('Existing vault identity changed')
        vault.ticket['repository_id']=identity;save_ticket(existing,vault.ticket)
        return existing
    if repository.exists():raise FileExistsError('Use a NEW directory for the encrypted vault')
    key_dir=secure_directory(key_dir)
    key=key_dir/'password.key'
    with key.open('x',encoding='ascii') as stream:stream.write(secrets.token_urlsafe(48)+'\n')
    if os.name!='nt':key.chmod(0o600)
    ticket={'format':FORMAT,'key_file':key.name,'storage':'local-encrypted','repository':str(repository)}
    path=key_dir/'recovery.json';save_ticket(path,ticket)
    vault=Vault(path,tools)
    vault.json(['init','--repository-version','2'])
    ticket['repository_id']=vault.json(['cat','config'])['id'];save_ticket(path,ticket)
    return path


def publish(ticket_path,remote,rclone_config=None,tools=None,allow_local_test=False):
    remote=validate_remote(remote);vault=Vault(ticket_path,tools,rclone_config)
    if vault.ticket['storage']!='local-encrypted':raise ValueError('Already published; create later snapshots directly in the configured cloud vault')
    if 'snapshot' not in vault.ticket:raise ValueError('Back up and verify a snapshot before publishing')
    source=private.outside(vault.repository)
    if vault.key.is_relative_to(source):raise ValueError('Unlock key must never be uploaded')
    for base,dirs,names in os.walk(source):
        for name in [*dirs,*names]:
            path=Path(base,name);relative=path.relative_to(source)
            reject_link(path)
            if not path.resolve().is_relative_to(source):raise ValueError('Encrypted repository path escapes its boundary')
            if relative.parts[0] not in {'config','data','index','snapshots','keys','locks'}:raise ValueError('Unrecognized file in encrypted repository; upload stopped')
            if path.is_file() and relative.as_posix()!='config' and not re.fullmatch('[0-9a-f]{64}',path.name):
                raise ValueError('Unrecognized plaintext/object filename; upload stopped')
    available=subprocess.run([vault.tools['rclone'],'listremotes','--json'],env=vault.env,capture_output=True,text=True,encoding='utf8')
    if available.returncode:raise RuntimeError('Could not read locally configured cloud remotes')
    providers=json.loads(available.stdout)
    records=providers.get('remotes',[]) if isinstance(providers,dict) else providers
    selected=next((r for r in records if r['name'].rstrip(':')==remote.split(':',1)[0]),None)
    if selected is None:raise ValueError('Cloud remote is not configured; log in locally with rclone config first')
    local_test=selected['type'] in {'local','memory'}
    if local_test and not allow_local_test:raise ValueError('This is local test storage, not a cloud provider')
    if selected['type'] in {'alias','crypt','chunker','union','combine','internetarchive','http'}:
        raise ValueError('Select a direct private storage remote; wrapped/public/read-only backends are not accepted')
    created=subprocess.run([vault.tools['rclone'],'mkdir',remote],env=vault.env,capture_output=True)
    if created.returncode:raise RuntimeError('Cannot create/open the dedicated cloud folder; check local login and permissions')
    listing=subprocess.run([vault.tools['rclone'],'lsf',remote,'--max-depth','1'],env=vault.env,capture_output=True,text=True,encoding='utf8')
    if listing.returncode:raise RuntimeError('Cannot inspect cloud destination safely')
    existing=set(listing.stdout.splitlines())
    if existing:
        if 'config' not in existing or not existing<={'config','data/','index/','snapshots/','keys/','locks/'}:
            raise ValueError('Cloud folder contains unrelated files; choose a new dedicated folder')
        Vault(ticket_path,vault.tools,rclone_config,repository='rclone:'+remote).check_identity()
    # Only the restic repository is sent. Never upload its parent or the key folder.
    result=subprocess.run([vault.tools['rclone'],'copy',str(source),remote,'--immutable','--checksum','--transfers','2','--checkers','2'],env=vault.env,capture_output=True)
    if result.returncode:raise RuntimeError('Ciphertext upload failed; cloud credentials stay local. Retry copies only missing/changed encrypted objects.')
    cloud=Vault(ticket_path,vault.tools,rclone_config,repository='rclone:'+remote)
    cloud.verify()
    vault.ticket.update(storage='transport-test' if local_test else 'cloud',repository='rclone:'+remote)
    save_ticket(vault.path,vault.ticket)
    return {'status':'transport_test_verified' if local_test else 'cloud_verified','snapshot':vault.ticket['snapshot'],'plaintext_uploaded':False,'unlock_secret_uploaded':False}


def recover(ticket_path,destination,cache_dir=None,rclone_config=None,allow_incomplete=False,install=True,tools=None,quark_client=None):
    _,record,_=load_ticket(ticket_path);destination=private.outside(destination)
    if not record['complete'] and not allow_incomplete:raise ValueError('Historical originals are missing; use --allow-incomplete only after reviewing that status')
    reuse=destination.exists()
    if reuse:
        report=destination/'restore-report.json'
        if not report.is_file() or private.read(report).get('archive_sha256')!=record['archive_sha256']:
            raise FileExistsError('Restore destination contains unrelated knowledge; choose a new directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    cache=local_only(cache_dir or destination.parent/(destination.name+'-download'))
    needed=(0 if reuse else record['restore_bytes'])+256*1024*1024
    if not (cache/record['archive_name']).exists():
        staged=cache/('.download-'+record['snapshot'])/record['archive_name']
        needed+=max(0,record['archive_bytes']-(staged.stat().st_size if staged.is_file() else 0))
    if record['storage']=='quark':needed+=sum(o['bytes'] for o in record['quark']['objects'])
    if shutil.disk_usage(destination.parent).free<needed:raise OSError('Insufficient disk space for download and independent restored data')
    repository=None
    if record['storage']=='quark':
        import quark_transport
        repository=str(quark_transport.materialize(ticket_path,cache/'ciphertext',quark_client or quark_transport.Client()))
    vault=Vault(ticket_path,tools,rclone_config,repository=repository)
    archive=vault.download(cache)
    if install:
        command=[sys.executable,str(ROOT/'scripts/install.py'),'--private-backup',str(archive),'--restore-to',str(destination)]
        if allow_incomplete:command.append('--allow-incomplete-backup')
        subprocess.run(command,check=True)
    elif reuse:private.verify_restored(archive,destination,allow_incomplete)
    else:private.restore(archive,destination,allow_incomplete)
    return {'status':'restored','complete':vault.ticket['complete'],'missing_originals':vault.ticket['missing_originals'],'installed':install}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--rclone-config');parser.add_argument('--quark-skill');parser.add_argument('--session-input');parser.add_argument('--session-id');sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('init');p.add_argument('--key-dir',required=True);p.add_argument('--local-repository',required=True)
    p=sub.add_parser('backup');p.add_argument('--recovery',required=True);p.add_argument('--archive',required=True)
    p=sub.add_parser('publish');p.add_argument('--recovery',required=True);p.add_argument('--remote',required=True)
    p=sub.add_parser('verify');p.add_argument('--recovery',required=True)
    p=sub.add_parser('publish-quark');p.add_argument('--recovery',required=True)
    p=sub.add_parser('verify-quark');p.add_argument('--recovery',required=True);p.add_argument('--cache-dir',required=True)
    p=sub.add_parser('backup-quark');p.add_argument('--recovery',required=True);p.add_argument('--archive',required=True);p.add_argument('--cache-dir',required=True)
    p=sub.add_parser('restore');p.add_argument('--recovery',required=True);p.add_argument('--destination',required=True);p.add_argument('--cache-dir');p.add_argument('--allow-incomplete',action='store_true');p.add_argument('--skip-install',action='store_true')
    a=parser.parse_args()
    def quark_client():
        import quark_transport
        return quark_transport.Client(a.quark_skill,a.session_input,a.session_id)
    if a.action=='init':result={'status':'initialized_locally','recovery_file':str(initialize(a.key_dir,a.local_repository))}
    elif a.action=='backup':result=Vault(a.recovery,rclone_config=a.rclone_config).backup(a.archive)
    elif a.action=='publish':result=publish(a.recovery,a.remote,a.rclone_config)
    elif a.action=='verify':result=Vault(a.recovery,rclone_config=a.rclone_config).verify()
    elif a.action=='publish-quark':
        import quark_transport
        result=quark_transport.publish(a.recovery,quark_client())
    elif a.action=='verify-quark':
        import quark_transport
        result=quark_transport.verify(a.recovery,a.cache_dir,quark_client())
    elif a.action=='backup-quark':
        import quark_transport
        result=quark_transport.backup(a.recovery,a.archive,a.cache_dir,quark_client())
    else:result=recover(a.recovery,a.destination,a.cache_dir,a.rclone_config,a.allow_incomplete,not a.skip_install,quark_client=quark_client() if load_ticket(a.recovery)[1]['storage']=='quark' else None)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError,KeyError) as error:
        print('Cloud backup stopped: '+str(error),file=sys.stderr);raise SystemExit(1)

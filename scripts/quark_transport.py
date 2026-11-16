"""Quark's official installed CLI as a ciphertext-only transport.

No account tokens, CLI runtime, or recovery records are bundled in this checkout.
Remote file identifiers and hashes live beside the offline recovery key.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import optics_private as private


class TransferError(RuntimeError):
    def __init__(self,code,provider_message=''):
        self.code=code
        self.retryable=code in {1007,-1704} or (code==-100 and any(marker in provider_message.lower() for marker in ['socket disconnected','econnreset','etimedout','tls connection','request timeout after']))
        message='Quark transfer failed (code '+str(code)+'); inspect the local provider result. Successful objects remain checkpointed.'
        if code in {-1408,-118}:message+=' Log in locally with the official Quark CLI login command, then retry; never send credentials in chat.'
        super().__init__(message)


class TransferIdleTimeout(TransferError):
    """The owned CLI was terminated after a bounded interval without progress."""
    def __init__(self):
        super().__init__(-100,'Request timeout after CLI idle deadline')


def download_mode(help_text):
    if re.search(r'^\s+download\s+\[',help_text,re.M):return 'download'
    if re.search(r'^\s+read-file\s+\[',help_text,re.M):return 'read-file'
    raise ValueError('Installed Quark CLI has no supported file retrieval command; repair/update the official skill')


def install_skill(destination):
    """Bootstrap official files globally; never vendor runtime or credentials."""
    destination=private.outside(destination)
    if destination.exists():raise ValueError('Quark skill directory is incomplete; repair it with its official installer')
    spec=private.read(Path(__file__).resolve().parents[1]/'quark-tool.json')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='quark-bootstrap-',dir=destination.parent) as temporary:
        archive=Path(temporary)/'official.zip'
        with urllib.request.urlopen(spec['url'],timeout=60) as source,archive.open('wb') as output:
            shutil.copyfileobj(source,output,1024*1024)
        if private.sha(archive)!=spec['sha256']:raise ValueError('Official Quark package checksum mismatch')
        staging=Path(temporary)/'skill';staging.mkdir()
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                target=(staging/item.filename).resolve()
                if not target.is_relative_to(staging) or '\\' in item.filename or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('Unsafe path in official Quark package')
            package.extractall(staging)
        for name in ['SKILL.md','scripts/install.sh','scripts/quark-drive.cjs']:
            if not (staging/name).is_file():raise ValueError('Incomplete official Quark package')
        os.replace(staging,destination)


def safe_relative(value):
    if not isinstance(value,str) or '\\' in value or ':' in value:
        raise ValueError('Unsafe encrypted object path')
    path=PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix()!=value:
        raise ValueError('Unsafe encrypted object path')
    if value=='config':return path
    if len(path.parts)==2 and path.parts[0] in {'keys','index','snapshots'} and re.fullmatch('[0-9a-f]{64}',path.name):return path
    if len(path.parts)==3 and path.parts[0]=='data' and re.fullmatch('[0-9a-f]{2}',path.parts[1]) and re.fullmatch('[0-9a-f]{64}',path.name) and path.name.startswith(path.parts[1]):return path
    raise ValueError('Unexpected plaintext or object in encrypted repository')


def validate_objects(objects,complete=True):
    if not isinstance(objects,list) or not objects:raise ValueError('Missing Quark object inventory')
    paths=set();fids=set()
    for obj in objects:
        safe_relative(obj['path'])
        if obj['path'] in paths:raise ValueError('Duplicate encrypted object path')
        paths.add(obj['path'])
        if not re.fullmatch('[0-9a-f]{64}',obj['sha256']) or type(obj['bytes']) is not int or obj['bytes']<0:
            raise ValueError('Invalid ciphertext checksum or size')
        fid=obj.get('fid')
        if complete or fid:
            if not isinstance(fid,str) or not fid or fid.startswith('-') or re.search(r'[\s\x00-\x1f]',fid) or fid in fids:
                raise ValueError('Missing, unsafe or duplicate Quark file identity')
            fids.add(fid)
    if 'config' not in paths or not any(p.startswith('keys/') for p in paths) or not any(p.startswith('snapshots/') for p in paths):
        raise ValueError('Incomplete encrypted repository inventory')


class Client:
    def __init__(self,skill_dir=None,session_input=None,session_id=None,workers=3):
        if type(workers) is not int or not 1<=workers<=64:raise ValueError('Quark read workers must be between 1 and 64')
        self.workers=workers
        self.skill=Path(skill_dir or Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'skills/quarkclouddrive').expanduser().resolve()
        self.node=shutil.which('node')
        if not self.node:raise ValueError('Install Node.js 16+ before using Quark backup')
        if not (self.skill/'scripts/install.sh').is_file():install_skill(self.skill)
        self.session=session_id or str(int(time.time()))+'-'+secrets.token_hex(3)
        if not re.fullmatch(r'\d+-[a-zA-Z0-9]{6}',self.session):raise ValueError('Invalid Quark session ID')
        self.session_input=session_input
        self.checked=False;self.updated=False;self.setup_lock=threading.Lock();self.read_mode=None

    def prepare(self):
        with self.setup_lock:self.setup()

    def setup(self):
        if self.checked:return
        candidates=[Path(os.environ.get('ProgramFiles',''))/'Git/bin/bash.exe'] if os.name=='nt' else []
        bash=next((str(p) for p in candidates if p.is_file()),None) or shutil.which('bash')
        if not bash:raise ValueError('Install Git Bash (Windows) or bash (Linux) for the official Quark installer')
        result=subprocess.run([bash,'scripts/install.sh'],cwd=self.skill,capture_output=True,text=True,encoding='utf8',timeout=120)
        if result.returncode:raise RuntimeError('Official Quark installation check failed; run its install.sh locally to diagnose')
        for line in result.stdout.splitlines():
            try:record=json.loads(line)
            except ValueError:continue
            if record.get('type')=='install_result':self.updated=bool(record.get('success') and record.get('updated'))
        command=[self.node,str(self.skill/'scripts/quark-drive.cjs'),'--help','--session-id',self.session]
        if self.session_input is not None:command+=['--session-input',self.session_input]
        help_result=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=30)
        if help_result.returncode:raise ValueError('Could not check the official Quark CLI capabilities')
        self.read_mode=download_mode(help_result.stdout)
        self.checked=True

    def run(self,args,runtime,on_record=None):
        with self.setup_lock:self.setup()
        runtime=private.outside(runtime);runtime.mkdir(parents=True,exist_ok=True)
        command=[self.node,str(self.skill/'scripts/quark-drive.cjs'),*args,'--session-id',self.session]
        if self.session_input is not None:command+=['--session-input',self.session_input]
        if self.updated:command+=['--skill-updated']
        env=os.environ.copy();env['OPENCLAW_RUNTIME_DIR']=str(runtime)
        final=None;records=[];last=-1
        with tempfile.TemporaryFile() as errors:
            child=subprocess.Popen(command,cwd=runtime,env=env,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf8')
            timeout=[False]
            def expire():
                timeout[0]=True
                if child.poll() is None:child.terminate()
            timer=threading.Timer(300,expire);timer.daemon=True;timer.start()
            try:
                for line in child.stdout:
                    timer.cancel();timer=threading.Timer(300,expire);timer.daemon=True;timer.start()
                    try:item=json.loads(line)
                    except ValueError:continue
                    if item.get('type')=='progress':
                        percent=item.get('data',{}).get('percent',0)
                        if percent>=last+5:print('Quark transfer:',percent,'%',flush=True);last=percent
                    else:
                        records.append(item)
                        if on_record:on_record(item)
                    if item.get('type')=='result':
                        final=item
                        # Transfer commands have no post-result artifacts. SDK timers
                        # may outlive completion; stop only this owned CLI after a grace.
                        break
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=10)
            finally:
                timer.cancel()
                child.stdout.close()
                if child.poll() is None:child.terminate();child.wait(timeout=10)
        if final is None:
            if timeout[0]:raise TransferIdleTimeout()
            raise RuntimeError('Quark CLI ended without a completed result; retained checkpoints can be retried')
        notice=final.get('notice',{}).get('text')
        if notice:print(notice,flush=True)
        if final.get('code')!=0 or final.get('data',{}).get('failCount',0):
            # Service messages may include signed URLs. Keep the complete provider
            # result locally, and expose only a safe failure category to automation.
            private.write(runtime/'last-provider-result.json',final)
            raise TransferError(final.get('code'),final.get('msg',''))
        return final,records

    def read(self,obj,runtime,receive):
        for attempt in range(3):
            try:return self._read_once(obj,runtime,receive)
            except TransferError as error:
                if not error.retryable or attempt==2:raise
                print('Quark network interruption; retrying this ciphertext read',flush=True)
                time.sleep(5*(attempt+1))

    def _read_once(self,obj,runtime,receive):
        # 1.0.25's shipped CLI exposes download, although its reference document
        # describes read-file. Use the actual --help contract, including output dir.
        with self.setup_lock:self.setup()
        if self.read_mode=='download':
            final,_=self.run(['download','--fid',obj['fid'],'--output-dir',str(runtime)],runtime)
            data=final.get('data',{})
        else:
            final,records=self.run(['read-file','--fid',obj['fid']],runtime)
            matches=[r['data'] for r in records if r.get('type')=='list' and r.get('code')==0 and r.get('data',{}).get('fid')==obj['fid']]
            if len(matches)!=1:raise ValueError('Quark returned an ambiguous downloaded object')
            data=matches[0]
        if not data.get('filePath'):raise ValueError('Quark returned no downloaded file')
        receive({'type':'list','code':0,'data':{**data,'fid':obj['fid']}})


def inventory(source):
    import optics_cloud as cloud
    source=cloud.local_only(source);cloud.reject_link(source)
    objects=[];names=set()
    for base,dirs,files in os.walk(source):
        for name in [*dirs,*files]:cloud.reject_link(Path(base,name))
        for name in files:
            file=Path(base,name);relative=file.relative_to(source).as_posix()
            # A verified readback can become the retained local mirror. These
            # root-only local receipts must never be sent back to the provider.
            if relative in {'.quark-cache.json','.quark-readback-progress.json'}:continue
            safe_relative(relative)
            if name in names:raise ValueError('Ambiguous encrypted object name')
            names.add(name)
            objects.append({'path':relative,'bytes':file.stat().st_size,'sha256':private.sha(file)})
    objects.sort(key=lambda x:x['path']);validate_objects(objects,complete=False)
    return objects


def publish(ticket_path,client,tools=None):
    import optics_cloud as cloud
    vault=cloud.Vault(ticket_path,tools)
    if vault.ticket['storage']!='local-encrypted':raise ValueError('Quark publishing starts from a verified local encrypted snapshot')
    if 'snapshot' not in vault.ticket:raise ValueError('Create and verify the encrypted snapshot first')
    vault.check_identity();source=cloud.local_only(vault.repository)
    if vault.key.is_relative_to(source):raise ValueError('Unlock key must never be uploaded')
    objects=inventory(source)
    old=vault.ticket.get('quark',{})
    # Restic objects are immutable. Reuse matching ciphertext across snapshots,
    # not just across retries, so updates do not duplicate the entire cloud vault.
    previous={obj['path']:obj for obj in old.get('objects',[])}
    for obj in objects:
        existing=previous.get(obj['path'],{})
        if existing.get('sha256')==obj['sha256'] and existing.get('bytes')==obj['bytes'] and existing.get('fid'):obj['fid']=existing['fid']
    record={'snapshot':vault.ticket['snapshot'],'objects':objects,'verified':False}
    vault.ticket['quark']=record;cloud.save_ticket(vault.path,vault.ticket)
    by_name={PurePosixPath(o['path']).name:o for o in objects};checkpoint_lock=threading.Lock()
    def checkpoint(item):
        if item.get('type')=='list' and item.get('code')==0:
            data=item['data'];obj=by_name.get(data.get('fileName'))
            if obj is None or data.get('fileSize')!=obj['bytes']:raise ValueError('Unexpected object returned by upload')
            with checkpoint_lock:
                obj['fid']=data['fileId'];cloud.save_ticket(vault.path,vault.ticket)
    pending=[obj for obj in objects if not obj.get('fid')]
    runtime=vault.path.parent/'quark-runtime'
    client.prepare()
    # Send exact approved files. Restic pre-creates hundreds of empty folders;
    # traversing them through a drive API is unnecessary. The offline inventory
    # reconstructs their original paths from immutable file identities.
    # No parent directory supplied: honor the official CLI's default scope.
    def upload_batch(pair):
        start,batch=pair
        final=None
        for attempt in range(3):
            remaining=[o for o in batch if not o.get('fid')]
            if not remaining:break
            try:
                final,_=client.run(['upload',*[str(source/o['path']) for o in remaining]],runtime/str(start),checkpoint)
                break
            except TransferError as error:
                if not error.retryable or attempt==2:raise
                print('Quark network interruption; retaining confirmed files and retrying missing objects',flush=True)
                time.sleep(5*(attempt+1))
        with checkpoint_lock:
            if final and final.get('data',{}).get('fullPath'):record['full_path']=final['data']['fullPath']
            cloud.save_ticket(vault.path,vault.ticket)
            print('Ciphertext uploaded:',sum(bool(o.get('fid')) for o in objects),'/',len(objects),flush=True)
    # Bound subprocesses and stop admitting work when a batch fails.
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches=[(n,pending[n:n+24]) for n in range(0,len(pending),24)]
        for start in range(0,len(batches),2):list(pool.map(upload_batch,batches[start:start+2]))
    validate_objects(objects)
    record['uploaded']=True;cloud.save_ticket(vault.path,vault.ticket)
    return {'status':'quark_uploaded_pending_readback','objects':len(objects),'bytes':sum(o['bytes'] for o in objects),'full_path':record.get('full_path','')}


def materialize(ticket_path,destination,client,fresh=False):
    import optics_cloud as cloud
    path,ticket,key=cloud.load_ticket(ticket_path)
    record=ticket.get('quark',{});objects=record.get('objects');validate_objects(objects)
    destination=cloud.local_only(destination);cloud.reject_link(destination)
    if key.is_relative_to(destination):raise ValueError('Ciphertext cache cannot contain the offline key')
    destination.mkdir(parents=True,exist_ok=True)
    marker=destination/'.quark-cache.json'
    cloud.reject_link(marker)
    expected={'repository_id':ticket['repository_id'],'snapshot':ticket['snapshot']}
    if marker.exists():
        if private.read(marker)!=expected:raise ValueError('Cache belongs to a different encrypted snapshot')
    elif any(destination.iterdir()):raise ValueError('Choose an empty dedicated Quark ciphertext cache')
    else:private.write(marker,expected)
    pending=[];missing_bytes=0;confirmed=0;confirmed_bytes=0
    for obj in objects:
        target=destination/obj['path']
        for parent in [target,*target.parents]:
            if parent==destination.parent:break
            cloud.reject_link(parent)
        if target.exists():
            if not target.is_file() or target.stat().st_size!=obj['bytes'] or private.sha(target)!=obj['sha256']:
                raise ValueError('Ciphertext cache changed or corrupted; use a fresh cache instead of overwriting')
            if fresh:pending.append(obj)
            else:confirmed+=1;confirmed_bytes+=obj['bytes']
        else:pending.append(obj);missing_bytes+=obj['bytes']
    if shutil.disk_usage(destination).free<missing_bytes+256*1024*1024:
        raise OSError('Insufficient disk space for encrypted Quark readback')
    runtime=destination.parent/(destination.name+'-transfer')
    cloud.reject_link(runtime)
    progress_lock=threading.Lock()
    progress_path=destination/'.quark-readback-progress.json'
    cloud.reject_link(progress_path)
    def save_progress(status):
        cloud.save_ticket(progress_path,{'status':status,'snapshot':ticket['snapshot'],'objects':len(objects),'verified_objects':confirmed,'verified_bytes':confirmed_bytes,'total_bytes':sum(o['bytes'] for o in objects),'updated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'mode':'fresh' if fresh else 'resumed'})
    save_progress('reading')
    if pending:client.prepare()
    workers=getattr(client,'workers',3)
    if type(workers) is not int or not 1<=workers<=64:raise ValueError('Invalid Quark read concurrency')
    batch_size=max(24,workers*2)
    for start in range(0,len(pending),batch_size):
        batch=pending[start:start+batch_size];wanted={o['fid']:o for o in batch};received=set()
        def receive(item):
            nonlocal confirmed,confirmed_bytes
            if item.get('type')!='list' or item.get('code')!=0:return
            data=item['data'];obj=wanted.get(data.get('fid'))
            if obj is None or data.get('fid') in received:raise ValueError('Unexpected or duplicate downloaded object')
            downloaded=Path(data['filePath']).resolve();cloud.reject_link(downloaded)
            if not downloaded.is_relative_to(runtime.resolve()):raise ValueError('Quark returned a file outside the assigned transfer directory')
            if downloaded.stat().st_size!=obj['bytes'] or private.sha(downloaded)!=obj['sha256']:
                raise ValueError('Cloud ciphertext SHA256 verification failed')
            target=destination/obj['path'];target.parent.mkdir(parents=True,exist_ok=True)
            cloud.reject_link(target)
            if target.exists():
                if not fresh or private.sha(target)!=obj['sha256']:raise ValueError('Concurrent change in ciphertext cache')
                downloaded.unlink()
            else:os.replace(downloaded,target)
            with progress_lock:
                received.add(obj['fid']);confirmed+=1;confirmed_bytes+=obj['bytes'];save_progress('reading')
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda obj:client.read(obj,runtime/obj['sha256'],receive),batch))
        if received!=set(wanted):raise ValueError('Quark did not return every requested ciphertext object')
        print('Ciphertext readback:',confirmed,'/',len(objects),flush=True)
    save_progress('objects_verified')
    return destination


def verify(ticket_path,cache_dir,client,tools=None,resume=False):
    import optics_cloud as cloud
    path,ticket,_=cloud.load_ticket(ticket_path)
    if Path(ticket['repository']).is_absolute() and Path(cache_dir).resolve()==Path(ticket['repository']).resolve():
        raise ValueError('Cloud verification needs an independent readback cache')
    if resume and ticket.get('quark',{}).get('verified'):raise ValueError('Completed cloud verification requires a fresh read; resume is only for an unfinished snapshot')
    repository=materialize(path,cache_dir,client,fresh=not resume)
    result=cloud.Vault(path,tools,repository=str(repository)).verify()
    ticket['quark']['verified']=True;ticket['quark']['verified_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    # Keep the original local mirror for incremental future uploads and rollback.
    if ticket['storage']=='local-encrypted':ticket['quark']['local_repository']=ticket['repository']
    ticket['storage']='quark';ticket['repository']='quark:offline-object-inventory'
    cloud.save_ticket(path,ticket)
    return {**result,'storage':'quark','status':'cloud_verified','objects':len(ticket['quark']['objects'])}


def backup(ticket_path,archive,cache_dir,client,tools=None):
    """Keep the current cloud locator usable until the next snapshot is verified."""
    import optics_cloud as cloud
    path,ticket,_=cloud.load_ticket(ticket_path)
    work=path
    if ticket['storage']=='quark':
        work=path.with_name('next-recovery.json')
        source=ticket['quark'].get('local_repository')
        if not source or not Path(source).is_dir():raise ValueError('The local encrypted mirror is required to append a snapshot; restore the ciphertext mirror first')
        if not work.exists():
            updated={**ticket,'storage':'local-encrypted','repository':source}
            cloud.save_ticket(work,updated)
        else:
            _,pending,_=cloud.load_ticket(work)
            if pending['repository_id']!=ticket['repository_id']:raise ValueError('Another pending recovery exists; retain it for inspection')
    _,pending,_=cloud.load_ticket(work)
    if pending['storage']=='quark':
        if private.sha(archive)!=pending['archive_sha256']:raise ValueError('A different update already awaits commit; finish it first')
    else:
        vault=cloud.Vault(work,tools)
        if private.sha(archive)!=vault.ticket.get('archive_sha256'):vault.backup(archive)
        publish(work,client,tools)
    result=verify(work,Path(cache_dir)/cloud.load_ticket(work)[1]['snapshot'],client,tools)
    if work!=path:
        cloud.save_ticket(path.with_name('previous-recovery.json'),ticket)
        cloud.save_ticket(path,cloud.load_ticket(work)[1])
        work.unlink()
    return result

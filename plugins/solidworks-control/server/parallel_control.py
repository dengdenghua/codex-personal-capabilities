"""Opt-in isolated-instance broker. A pool holds the legacy lock until released.

Per-session busy records serialize COM. Workspace ownership persists between jobs.
An OS file lock protects metadata only; no COM call runs under that file lock.
"""
from pathlib import Path
from contextlib import contextmanager
import json, os, sys, time, uuid, subprocess, msvcrt
import jobs

ROOT = Path(__file__).resolve().parent
STATE = jobs.DATA / 'parallel-state'
ALLOWED = {'session','open','inspect','components','mate_status','geometry_inventory',
           'interference','view','activate','save_copy','close_clean',
           'create_part','create_assembly','create_drawing'}

def key(path):
    p = Path(path)
    if not p.is_absolute(): raise ValueError('Absolute path required')
    # Resolve junctions and symlinks; reject links to avoid mutable alias ownership.
    for parent in [p, *p.parents]:
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Symlink/junction workspace paths are not supported')
    return os.path.normcase(str(p.resolve()))

def inside(path, root):
    p, r = key(path), key(root)
    try: return p != r and os.path.commonpath([p,r]) == r
    except ValueError: return False

def overlap(a,b):
    a,b = key(a),key(b)
    try: return os.path.commonpath([a,b]) in (a,b)
    except ValueError: return False

@contextmanager
def transaction():
    STATE.mkdir(exist_ok=True)
    with (STATE/'registry.guard').open('a+b') as f:
        if f.tell() == 0: f.write(b'0'); f.flush()
        end = time.monotonic()+10
        while True:
            try:
                f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); break
            except OSError:
                if time.monotonic()>end: raise TimeoutError('Registry busy; no CAD action submitted')
                time.sleep(.05)
        try:
            file=STATE/'registry.json'
            state=json.loads(file.read_text('utf-8')) if file.exists() else {'version':1,'pool':None,'sessions':{}}
            try: yield state
            finally: jobs.atomic(file,state)
        finally:
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def ensure_pool(s):
    if any(p['name'].lower()=='efdsolver.exe' for p in jobs.health()['processes']):
        raise RuntimeError('Flow solver is running; parallel CAD admission remains exclusive')
    if s['pool']:
        lock=jobs.health()['lock']
        if not lock or lock.get('job_id')!=s['pool'] or lock.get('kind')!='isolated_instance_pool':
            raise RuntimeError('Pool barrier changed; refusing COM work')
        return
    jid=uuid.uuid4().hex
    try: fd=os.open(jobs.LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise RuntimeError('Legacy CAD job is running; parallel pool not started')
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump({'job_id':jid,'created':time.time(),'kind':'isolated_instance_pool','instruction':'Use parallel health. Do not remove this barrier; release registered sessions normally.'},f)
    s['pool']=jid
    folder=jobs.JOBS/jid;folder.mkdir()
    jobs.atomic(folder/'request.json',{'action':'isolated_instance_pool','args':{}})
    jobs.atomic(folder/'stage.json',{'stage':'pool_owns_legacy_barrier','time':time.time()})

def end_pool_if_empty(s):
    if s['sessions'] or not s['pool']: return
    jid=s['pool']
    jobs.atomic(jobs.JOBS/jid/'result.json',{'status':'completed','job_id':jid,'result':{'pool_released':True}})
    if not jobs.release_recorded_job(jid): raise RuntimeError('Could not release owned pool barrier')
    s['pool']=None

def validate_args(action,args,root):
    if action not in ALLOWED: raise ValueError('Action not enabled for parallel mode: '+action)
    if not isinstance(args,dict): raise ValueError('args must be an object')
    def local(p):
        if not inside(p,root): raise ValueError('Path escapes exclusive workspace: '+str(p))
    for field in ('document','path','output_path'):
        if field in args: local(args[field])
    if action=='open' and Path(args['path']).suffix.lower() not in ('.sldprt','.sldasm','.slddrw'):
        raise ValueError('Parallel open supports native files only; neutral import remains exclusive')
    if action.startswith('create_'):
        plan=args['plan']
        if plan.get('template'): raise ValueError('Use installed default templates in parallel mode')
        if plan.get('part'): local(plan['part'])
        for item in plan.get('components',[]): local(item['part'])
        for item in plan.get('exports',[]):
            if item.get('path'): local(item['path'])
        if action=='create_part' and not plan.get('verify'): raise ValueError('Analytic verify block required')

def launch_job(s,session,action,args):
    if session.get('busy'): return {'status':'busy','job_id':session['busy'],'session_id':session['id']}
    ensure_pool(s)
    jid=uuid.uuid4().hex;folder=jobs.JOBS/jid;folder.mkdir()
    jobs.atomic(folder/'request.json',{'action':action,'args':args,'session':dict(session)})
    session['busy']=jid
    # Persist reservation BEFORE launching, even if process metadata publication fails.
    jobs.atomic(STATE/'registry.json',s)
    process=None
    try:
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'parallel_worker.py'),jid],stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,cwd=ROOT)
        import psutil
        jobs.atomic(folder/'process.json',{'pid':process.pid,'created':psutil.Process(process.pid).create_time(),'started':time.time()})
    except Exception as exc:
        if process is not None:
            return {'status':'submitted','job_id':jid,'session_id':session['id'],'tracking_warning':str(exc)}
        jobs.atomic(folder/'result.json',{'status':'failed','job_id':jid,'error':'Worker not launched: '+str(exc),'retry_automatically':False})
        session['busy']=None
        raise
    return {'status':'submitted','job_id':jid,'session_id':session['id']}

def register(workspace,pid=None,created=None):
    from parallel_session import resources,identity
    resources()
    root=key(workspace)
    if Path(root).exists() and any(Path(root).iterdir()): raise ValueError('Registration requires a new or empty dedicated workspace')
    if pid is not None: identity(pid,created)
    with transaction() as s:
        if len(s['sessions']) >= 2: raise ValueError('Initial parallel release supports at most two isolated sessions')
        for other in s['sessions'].values():
            if overlap(root,other['workspace']): raise ValueError('Workspace already owned or overlaps another session')
            if pid is not None and other.get('pid')==int(pid): raise ValueError('PID already registered')
        ensure_pool(s)
        Path(root).mkdir(parents=True,exist_ok=True)
        sid=uuid.uuid4().hex
        record={'id':sid,'pid':int(pid) if pid is not None else None,'created':created,'workspace':root,'status':'initializing','owned_process':pid is None,'busy':None}
        s['sessions'][sid]=record
        return launch_job(s,record,'_start' if pid is None else '_claim',{})

def submit(session_id,action,args):
    with transaction() as s:
        record=s['sessions'][session_id]
        if record['status']!='ready': raise RuntimeError('Session is not ready; inspect health and failed job')
        validate_args(action,args,record['workspace'])
        return launch_job(s,record,action,args)

def release(session_id):
    with transaction() as s:
        return launch_job(s,s['sessions'][session_id],'_release',{})

def recover(session_id):
    """Only reconcile a durably finished worker; never unlock uncertain COM work."""
    with transaction() as s:
        record=s['sessions'][session_id];jid=record.get('busy')
        if not jid:return {'status':'idle'}
        path=jobs.JOBS/jid/'result.json'
        if not path.exists():raise RuntimeError('No terminal result; lease retained. Never retry uncertain CAD writes')
        # Worker writes terminal result only after COM stops. Reconciliation is metadata only.
        result=json.loads(path.read_text('utf-8'))
        if result['status'] not in ('completed','failed'):raise RuntimeError('Result is not terminal')
        record['busy']=None
        return {'status':'reconciled','job_id':jid,'result_status':result['status']}

def health():
    with transaction() as s:
        result=json.loads(json.dumps(s))
    result['os']=jobs.health()
    for record in result['sessions'].values():
        if record.get('busy'):record['job']=jobs.status(record['busy'])
    return result

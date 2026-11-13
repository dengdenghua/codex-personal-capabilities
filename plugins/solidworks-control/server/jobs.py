"""Durable single-writer job broker. Never terminate SolidWorks or retry CAD writes."""
from pathlib import Path
import json,os,sys,time,uuid,subprocess,psutil
ROOT=Path(__file__).resolve().parent
from portable_paths import data_root
DATA=data_root();JOBS=DATA/'jobs';JOBS.mkdir(parents=True,exist_ok=True)
LOCK=DATA/'cad.lock'
def atomic(path,data):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    # Windows readers/AV can briefly hold the destination without delete sharing.
    # Retry only publishing metadata, never the CAD operation itself.
    try:
        for attempt in range(8):
            try:
                os.replace(tmp,path)
                break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.025*(attempt+1))
    finally:
        if tmp.exists():tmp.unlink()
def health():
    procs=[]
    for p in psutil.process_iter(['pid','name','create_time']):
        if (p.info['name'] or '').lower() in ('sldworks.exe','sldimport.exe','efdsolver.exe','fw_monitor.exe'):
            procs.append(p.info)
    try:
        lock=json.loads(LOCK.read_text('utf-8'))
    except FileNotFoundError:
        lock=None
    except (ValueError,OSError):
        lock={'status':'initializing_or_unreadable','instruction':'Wait; do not remove or bypass this lock.'}
    return {'processes':procs,'lock':lock}

def release_recorded_job(jid):
    """Release only an owned lock whose terminal result was durably published."""
    try:
        result=json.loads((JOBS/jid/'result.json').read_text('utf-8'))
        current=json.loads(LOCK.read_text('utf-8'))
        if result.get('job_id')==jid and result.get('status') in ('completed','failed') and current.get('job_id')==jid:
            LOCK.unlink()
            return True
    except (OSError,ValueError):
        pass
    return False
def submit(action,args):
    solvers=[p for p in health()['processes'] if p['name'].lower()=='efdsolver.exe']
    if solvers:return {'status':'busy','reason':'Flow solver is running; wait before submitting CAD operations','solvers':solvers}
    jid=uuid.uuid4().hex
    try:fd=os.open(LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:return {'status':'busy','active':health()['lock'],'instruction':'Inspect job_status. Do not resubmit while CAD state is uncertain.'}
    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump({'job_id':jid,'created':time.time()},f)
    p=None
    try:
        folder=JOBS/jid;folder.mkdir()
        atomic(folder/'request.json',{'action':action,'args':args})
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            p=subprocess.Popen([sys.executable,str(ROOT/'worker.py'),jid],stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW,cwd=ROOT)
        atomic(folder/'process.json',{'pid':p.pid,'created':psutil.Process(p.pid).create_time(),'started':time.time()})
    except Exception:
        if p is not None:
            # The worker may already be inside COM. Never unlock or resubmit.
            return {'status':'submitted','job_id':jid,'tracking_warning':'Worker launched but process metadata could not be published. Keep the lock and inspect this job; never retry automatically.'}
        if LOCK.exists() and json.loads(LOCK.read_text('utf-8')).get('job_id')==jid:LOCK.unlink()
        raise
    return {'status':'submitted','job_id':jid}
def status(jid):
    if len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):raise ValueError('Invalid job id')
    d=JOBS/jid
    if not d.exists():raise ValueError('Unknown job')
    if (d/'result.json').exists():return json.loads((d/'result.json').read_text('utf-8'))
    if (d/'request.json').exists():
        request=json.loads((d/'request.json').read_text('utf-8'))
        if request.get('action')=='isolated_instance_pool':
            return {'status':'managed_pool','job_id':jid,'instruction':'This is the opt-in parallel pool barrier, not a dead worker. Use sw_parallel_health and release its registered sessions normally. Do not acknowledge or remove the barrier.'}
    if not (d/'process.json').exists():
        elapsed=time.time()-d.stat().st_mtime
        return {'status':'starting' if elapsed<10 else 'uncertain','job_id':jid,
                'instruction':'Process tracking unavailable. Do not resubmit; inspect worker/SW state. Lock remains held.'}
    p=json.loads((d/'process.json').read_text('utf-8'))
    try:alive=psutil.Process(p['pid']).create_time()==p['created']
    except psutil.NoSuchProcess:alive=False
    elapsed=time.time()-p['started']
    return {'status':'running' if alive else 'uncertain','job_id':jid,'elapsed_seconds':round(elapsed,1),'long_running':elapsed>120,'stage':json.loads((d/'stage.json').read_text('utf-8')) if (d/'stage.json').exists() else None,'instruction':'Wait or inspect SW UI. Never assume timeout means action was cancelled.'}
def acknowledge(jid):
    s=status(jid)
    if s['status']!='uncertain':raise ValueError('Only a dead worker with no result can be acknowledged')
    current=health()['lock']
    if not current or current['job_id']!=jid:raise ValueError('Lock does not belong to this job')
    if health()['processes']:raise ValueError('SW/importer still running; inspect and close normally before clearing uncertain state')
    atomic(JOBS/jid/'acknowledged.json',{'time':time.time(),'note':'Dead worker and no SW/importer process. No automatic CAD retry.'});LOCK.unlink()
    return {'status':'released','job_id':jid}

"""One COM apartment/job, bound to one exact process and workspace."""
from pathlib import Path
import json,sys,time,traceback,subprocess,hashlib
import pythoncom,psutil
import jobs,parallel_control as broker
from parallel_session import connect,resources,identity,SKILL
sys.path.insert(0,str(SKILL))
from sw_connect import get_com_member as get

def document_rows(sw):
    return [{'path':get(d,'GetPathName'),'title':get(d,'GetTitle'),'dirty':bool(get(d,'GetSaveFlag'))} for d in (get(sw,'GetDocuments') or [])]

def check_documents(sw,root):
    rows=document_rows(sw)
    for row in rows:
        if not row['path'] or not broker.inside(row['path'],root):
            raise RuntimeError('Foreign or unsaved unnamed document in isolated session: '+str(row))
    return rows

def dependencies(sw,path,root):
    if not broker.inside(path,root) or not Path(path).is_file():raise ValueError('Input must exist inside the exclusive workspace')
    if Path(path).stat().st_nlink>1:raise ValueError('Hard-linked inputs are not isolated copies')
    deps=list(sw.GetDocumentDependencies2(str(path),True,True,False) or [])
    if len(deps)%2:raise RuntimeError('Unrecognized dependency listing')
    for p in deps[1::2]:
        if not broker.inside(p,root) or not Path(p).is_file() or Path(p).stat().st_nlink>1:
            raise ValueError('External, missing or hard-linked dependency: '+p)

def update_session(sid,**values):
    with broker.transaction() as state:state['sessions'][sid].update(values)

def run(req,folder,stage):
    session=req['session'];sid=session['id'];root=session['workspace'];action=req['action'];args=req['args']
    if action=='_start':
        resources();update_session(sid,launch_pending=True)
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        proc=subprocess.Popen([str(__import__('portable_paths').executable())],startupinfo=startup)
        session.update(pid=proc.pid,created=psutil.Process(proc.pid).create_time())
        update_session(sid,pid=session['pid'],created=session['created'],launch_pending=False)
        stage('waiting_for_exact_ROT',{'pid':session['pid']})
        deadline=time.monotonic()+150;last=None
        while True:
            identity(session['pid'],session['created'])
            try:sw=connect(session['pid'],session['created']);break
            except (RuntimeError,pythoncom.com_error) as exc:
                last=str(exc)
                if time.monotonic()>deadline:raise RuntimeError('Started process has no accessible exact ROT registration: '+last)
                time.sleep(1)
    else:
        if action=='_release' and session.get('pid') is None:
            if session.get('launch_pending'):raise RuntimeError('Uncertain process launch; cannot release reservation')
            return {'released':True,'never_bound':True}
        if action=='_release':
            try:
                p=psutil.Process(session['pid'])
                gone=p.create_time()!=session['created'] or p.num_threads()==0
            except psutil.NoSuchProcess:gone=True
            if gone:
                if any(p['name'].lower() in ('sldimport.exe','efdsolver.exe') for p in jobs.health()['processes']):
                    raise RuntimeError('Importer/solver still present; stale session retained')
                return {'released':True,'process_identity_no_longer_live':True,'no_process_terminated':True}
        resources(session['pid'],session['created']);sw=connect(session['pid'],session['created'])
    stage('bound_exact_process',{'pid':session['pid'],'created':session['created']})
    if action in ('_start','_claim'):
        rows=document_rows(sw)
        if rows:raise RuntimeError('Only EMPTY SolidWorks instances can be claimed; existing documents preserved')
        update_session(sid,status='ready')
        return {'session_id':sid,'pid':session['pid'],'created':session['created'],'workspace':root,'empty_instance_verified':True}
    if action=='_release':
        # No implicit save, close, discard or process termination. Caller must close
        # verified clean owned files with close_clean before releasing the instance.
        if document_rows(sw):raise RuntimeError('Close verified clean owned documents before release; nothing discarded')
        if session['owned_process']:
            get(sw,'ExitApp')
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try:
                    p=psutil.Process(session['pid'])
                    if p.create_time()!=session['created'] or p.num_threads()==0:break
                except psutil.NoSuchProcess:break
                time.sleep(.2)
            else:raise RuntimeError('Normal ExitApp has not finished; reservation retained')
        return {'released':True,'normal_exit_owned_empty_instance':session['owned_process']}
    broker.validate_args(action,args,root)
    before=check_documents(sw,root)
    if action=='open':dependencies(sw,args['path'],root)
    if action.startswith('create_'):
        plan=args['plan']
        if plan.get('part'):dependencies(sw,plan['part'],root)
        for item in plan.get('components',[]):dependencies(sw,item['part'],root)
    if action=='close_clean' and any(r['dirty'] for r in before):
        raise RuntimeError('A loaded document/dependency is dirty; no implicit discard allowed')
    if action in ('open','create_part','create_assembly','create_drawing'):
        from sw_document_recycler import assert_task_window_budget
        assert_task_window_budget(sw,[r['path'] for r in before],opening_path=args.get('path',args.get('output_path')))
    # Reuse tested operations in this worker process only. No global/shared runtime
    # monkeypatch persists; every connection remains tied to the same PID+epoch.
    import sw_connect,live_session,worker
    sw_connect.assert_capacity=lambda: resources(session['pid'],session['created'])
    live_session.connect_existing=lambda: connect(session['pid'],session['created'])
    worker.FOLDER=folder;worker.stage=stage
    stage('operation_start',{'action':action,'pid':session['pid']})
    start=time.time();result=worker.execute(action,args);end=time.time()
    after=check_documents(sw,root)
    identity(session['pid'],session['created'])
    return {'pid':session['pid'],'created':session['created'],'workspace':root,'operation_started':start,'operation_finished':end,'documents_before':before,'documents_after':after,'result':result}

def main(jid):
    folder=jobs.JOBS/jid;req=json.loads((folder/'request.json').read_text('utf-8'));sid=req['session']['id']
    def stage(name,data=None):jobs.atomic(folder/'stage.json',{'stage':name,'time':time.time(),'data':data})
    pythoncom.CoInitialize()
    try:
        result=run(req,folder,stage)
        report={'status':'completed','job_id':jid,'result':result}
    except BaseException as exc:
        report={'status':'failed','job_id':jid,'error':str(exc),'traceback':traceback.format_exc(),'retry_automatically':False}
    finally:pythoncom.CoUninitialize()
    # Publish result before clearing reservation. A failed publication retains it.
    jobs.atomic(folder/'result.json',report)
    with broker.transaction() as state:
        record=state['sessions'].get(sid)
        if record and record.get('busy')==jid:
            record['busy']=None
            if req['action']=='_release' and report['status']=='completed':del state['sessions'][sid]
            elif req['action']=='_claim' and report['status']=='failed':del state['sessions'][sid]
            elif req['action'] in ('_start','_claim') and report['status']=='failed':record['status']='attention'
        broker.end_pool_if_empty(state)

if __name__=='__main__':main(sys.argv[1])

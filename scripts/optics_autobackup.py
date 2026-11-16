"""Resumable scheduled backup runner. Configuration and every receipt stay local."""
import argparse
from contextlib import contextmanager,redirect_stdout
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import optics_cloud as cloud
import optics_private as private
import optics_incremental as incremental
import quark_transport as quark


def save(path,value):cloud.save_ticket(path,value)


@contextmanager
def stay_awake():
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:yield
    finally:
        if os.name=='nt':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


@contextmanager
def exclusive(path):
    path=Path(path);cloud.reject_link(path)
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,BlockingIOError):raise RuntimeError('backup_already_running')
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def due(state,now=None):
    if state.get('needs_attention'):return False
    now=now or datetime.now().astimezone()
    if state.get('pending') or state.get('cleanup_pending'):return time.time()>=state.get('retry_after',0)
    today=now.replace(hour=2,minute=0,second=0,microsecond=0)
    slot=today if now>=today else today-timedelta(days=1)
    return state.get('last_success_slot','')<slot.isoformat()


def slot():
    now=datetime.now().astimezone();today=now.replace(hour=2,minute=0,second=0,microsecond=0)
    return (today if now>=today else today-timedelta(days=1)).isoformat()


def verify_incremental(pending,previous,cache,client,tools=None):
    """Re-read each new cloud object; authenticate the whole local repository.

    Unchanged cloud identities are anchored to the previous completed readback,
    not claimed to have been freshly downloaded again during this run.
    """
    _,record,_=cloud.load_ticket(pending)
    if previous.get('storage')!='quark' or not previous.get('quark',{}).get('verified'):
        raise ValueError('A fully verified cloud checkpoint is required')
    if record['repository_id']!=previous['repository_id']:raise ValueError('Repository changed')
    cache=cloud.local_only(cache);cache.mkdir(parents=True,exist_ok=True)
    cloud.reject_link(cache)
    mark=cache/'checkpoint.json';identity={'repository_id':record['repository_id'],'snapshot':record['snapshot']}
    if mark.exists() and private.read(mark)!=identity:raise ValueError('Readback cache belongs to another checkpoint')
    save(mark,identity)
    old={o['path']:o for o in previous['quark']['objects']}
    objects=record['quark']['objects'];quark.validate_objects(objects)
    added=[o for o in objects if o!=old.get(o['path'])]
    if added:client.prepare()
    def read(obj):
        target=cache/obj['path'];cloud.reject_link(target)
        if target.exists():
            if target.stat().st_size!=obj['bytes'] or private.sha(target)!=obj['sha256']:raise ValueError('Readback cache changed')
            return
        runtime=cache/'transfer'/obj['sha256'];received=[]
        def receive(item):
            data=item['data'];downloaded=Path(data['filePath']).resolve()
            if data.get('fid')!=obj['fid'] or not downloaded.is_relative_to(runtime.resolve()):raise ValueError('Unexpected download')
            cloud.reject_link(downloaded)
            if downloaded.stat().st_size!=obj['bytes'] or private.sha(downloaded)!=obj['sha256']:raise ValueError('Cloud SHA256 mismatch')
            target.parent.mkdir(parents=True,exist_ok=True);os.replace(downloaded,target);received.append(True)
        client.read(obj,runtime,receive)
        if len(received)!=1:raise ValueError('Missing cloud readback receipt')
    with ThreadPoolExecutor(max_workers=min(8,getattr(client,'workers',3))) as pool:list(pool.map(read,added))
    vault=cloud.Vault(pending,tools,repository=record['repository'])
    vault.verify()
    record['quark'].update(verified=True,verified_at=datetime.now(timezone.utc).isoformat(),
                           verification_mode='new-cloud-objects-plus-full-local-authentication',
                           predecessor=previous['snapshot'],readback_objects=len(added),
                           readback_bytes=sum(o['bytes'] for o in added),
                           reused_cloud_objects=len(objects)-len(added),local_repository=vault.repository)
    record.update(storage='quark',repository='quark:offline-object-inventory');save(pending,record)
    return {'new_objects':len(added),'readback_bytes':sum(o['bytes'] for o in added),'reused_cloud_objects':len(objects)-len(added)}


def checkpoint(ticket_path,archive,cache,client,tools=None):
    path,current,_=cloud.load_ticket(ticket_path)
    pending=path.with_name('automatic-next-recovery.json')
    archive=Path(archive);digest=private.read(archive.with_suffix(archive.suffix+'.sha256.json'))['sha256']
    if current['storage']!='quark':raise ValueError('Current backup is not verified cloud storage')
    if current['archive_sha256']==digest:
        if private.sha(archive)!=digest:raise ValueError('Committed archive changed')
        if pending.exists():
            other=private.read(pending)
            if other.get('snapshot')!=current['snapshot']:raise ValueError('Another checkpoint remains pending')
            pending.unlink()
        return {'snapshot':current['snapshot'],'new_objects':current['quark'].get('readback_objects',0),
                'readback_bytes':current['quark'].get('readback_bytes',0),
                'reused_cloud_objects':current['quark'].get('reused_cloud_objects',0),'already_verified':True}
    if not pending.exists():
        staged={**current,'storage':'local-encrypted','repository':current['quark']['local_repository']}
        save(pending,staged)
    _,record,_=cloud.load_ticket(pending)
    if record['repository_id']!=current['repository_id']:raise ValueError('Pending repository changed')
    if record.get('automatic_parent') not in {None,current['snapshot']} and record['snapshot']!=current['snapshot']:
        raise ValueError('Pending checkpoint is based on another version')
    if record['storage']!='quark':
        if record['archive_sha256']!=digest:
            record['automatic_parent']=current['snapshot'];save(pending,record)
            cloud.Vault(pending,tools).backup(archive)
        quark.publish(pending,client,tools)
        result=verify_incremental(pending,current,cache,client,tools)
    else:
        if record['archive_sha256']!=digest:raise ValueError('Pending archive differs')
        result={'new_objects':record['quark']['readback_objects'],'readback_bytes':record['quark']['readback_bytes'],
                'reused_cloud_objects':record['quark']['reused_cloud_objects']}
    _,verified,_=cloud.load_ticket(pending)
    # Immutable offline rollback locators live beside the one local password file.
    for version in [current,verified]:
        history=path.with_name('recovery-'+version['snapshot']+'.json')
        if history.exists():
            saved=private.read(history)
            if any(saved.get(k)!=version.get(k) for k in ['repository_id','snapshot','archive_sha256']):
                raise ValueError('Historical version identity changed')
        else:save(history,version)
    save(path.with_name('previous-recovery.json'),current)
    save(path,verified)
    pending.unlink()
    return {**result,'snapshot':verified['snapshot']}


def error_kind(error):
    if isinstance(error,quark.TransferError):return 'network_retry_exhausted' if error.retryable else 'cloud_authorization_or_command'
    if isinstance(error,OSError):return 'local_io_or_space'
    if isinstance(error,ValueError):return 'integrity_or_source_validation'
    return 'backup_runtime_failure'


def versions(ticket):
    path,current,_=cloud.load_ticket(ticket)
    records={current['snapshot']:(path,current)}
    for p in path.parent.glob('recovery-*.json'):
        _,record,_=cloud.load_ticket(p)
        if record['repository_id']!=current['repository_id']:raise ValueError('Foreign version record')
        records[record['snapshot']]=(p,record)
    return sorted([{'snapshot':r['snapshot'],'verified_at':r['quark']['verified_at'],'archive_bytes':r['archive_bytes'],
                    'missing_originals':r['missing_originals'],'recovery_file':str(p),'current':r['snapshot']==current['snapshot']}
                   for p,r in records.values()],key=lambda r:r['verified_at'],reverse=True)


def cleanup_committed(cfg,state,job,previous_archive=None,previous_plan=None):
    """Delete exact regenerable files only; all cloud rollback versions remain."""
    work=Path(cfg['work_dir']).resolve();ticket,current,_=cloud.load_ticket(cfg['recovery'])
    archive=Path(state['archive']);expected=current['archive_sha256']
    if private.sha(archive)!=expected:raise ValueError('Active archive changed before cleanup')
    removals=[]
    if previous_archive:
        old=Path(previous_archive).resolve()
        if old!=archive.resolve() and old!=Path(cfg['baseline_archive']).resolve():
            if not old.is_relative_to(work) or old.name!='optics.private.zip':raise ValueError('Unsafe old archive path')
            checksum=old.with_suffix(old.suffix+'.sha256.json')
            if old.exists() or checksum.exists():
                old_hash=private.read(checksum)['sha256']
                retained=next((r for r in versions(ticket) if private.read(r['recovery_file'])['archive_sha256']==old_hash),None)
                if not retained:raise ValueError('Old checkpoint has no verified rollback locator')
                removals.extend([(old,old_hash),(checksum,None)])
    if previous_plan:
        old=Path(previous_plan).resolve()
        if old!=Path(state['seed_plan']).resolve() and old!=Path(cfg['seed_plan']).resolve():
            if not old.is_relative_to(work) or old.name!='private-plan.json':raise ValueError('Unsafe old plan path')
            removals.append((old,None))
    cache=Path(job['directory'])/'readback'
    for obj in current['quark']['objects']:
        target=cache/private.safe_relative(obj['path'])
        if target.is_file():removals.append((target,obj['sha256']))
    journal=Path(job['directory'])/'cleanup.jsonl'
    with journal.open('a',encoding='utf8') as out:
        for path,digest in removals:
            if not path.exists():continue
            cloud.reject_link(path)
            if not path.resolve().is_relative_to(work):raise ValueError('Cleanup outside automatic work directory')
            actual=private.sha(path)
            if digest and actual!=digest:raise ValueError('Cleanup file changed')
            row={'path':str(path),'sha256':actual,'bytes':path.stat().st_size,'replacement_snapshot':current['snapshot']}
            out.write(json.dumps({**row,'stage':'verified'})+'\n');out.flush()
            path.unlink();out.write(json.dumps({**row,'stage':'deleted'})+'\n');out.flush()


def run(config_path,force=False,client=None,tools=None):
    config_path=cloud.local_only(config_path);cfg=private.read(config_path)
    if cfg.get('format')!='optics-automatic-backup-v1':raise ValueError('Invalid local automatic backup profile')
    work=cloud.local_only(cfg['work_dir']);work.mkdir(parents=True,exist_ok=True);cloud.reject_link(work)
    ticket=cloud.local_only(cfg['recovery']);cloud.load_ticket(ticket)
    if ticket.is_relative_to(work):raise ValueError('Keep recovery secrets outside the staging directory')
    state_path=config_path.with_name('automatic-state.json');state=private.read(state_path) if state_path.exists() else {}
    if not force and not due(state):return {'status':'not_due'}
    with exclusive(work/'backup.lock'),stay_awake():
        state=private.read(state_path) if state_path.exists() else {}
        if not force and not due(state):return {'status':'not_due'}
        try:
            if state.get('cleanup_pending'):
                action=state['cleanup_pending']
                cleanup_committed(cfg,state,action['job'],action.get('archive'),action.get('plan'))
                state.pop('cleanup_pending');state.update(status='verified',retry_after=0,error=None,needs_attention=False);save(state_path,state)
                return {'status':'maintenance_completed','snapshot':state.get('snapshot')}
            job=state.get('pending')
            if not job:
                label=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                directory=work/label;directory.mkdir()
                job={'directory':str(directory),'archive':str(directory/'optics.private.zip'),'phase':'scan','slot':slot()}
                state.update(pending=job,status='running');save(state_path,state)
            directory=Path(job['directory']);archive=Path(job['archive'])
            if directory.parent!=work or archive.parent!=directory:raise ValueError('Unsafe pending job paths')
            cache=config_path.with_name('automatic-source-cache.json')
            if job['phase']=='scan':
                # A crash may occur after ZIP finalization but before the upload
                # phase is saved. Retire only this job's unpublished assembly,
                # after authenticating the retained baseline, then rebuild.
                plan=directory/'private-plan.json'
                incremental.refresh_plan(state.get('seed_plan',cfg['seed_plan']),plan,cfg.get('extra_roots',[]))
                partial=archive.with_suffix('.partial')
                if partial.exists() or archive.exists():
                    baseline=Path(state.get('archive',cfg['baseline_archive']))
                    expected=private.read(baseline.with_suffix(baseline.suffix+'.sha256.json'))['sha256']
                    if private.sha(baseline)!=expected:raise ValueError('Cannot retire partial checkpoint without valid baseline')
                    for staged in [partial,archive,archive.with_suffix(archive.suffix+'.sha256.json')]:
                        if not staged.exists():continue
                        cloud.reject_link(staged)
                        with (directory/'assembly-retirement.jsonl').open('a',encoding='utf8') as journal:
                            journal.write(json.dumps({'path':str(staged),'sha256':private.sha(staged),
                                'replacement':str(baseline),'replacement_sha256':expected,
                                'reason':'Retry unpublished task-owned archive assembly'})+'\n')
                        staged.unlink()
                full=time.time()-state.get('last_full_hash',0)>=7*86400
                result=incremental.build(plan,state.get('archive',cfg['baseline_archive']),archive,cache,full_hash=full)
                if result['status']=='unchanged':
                    os.replace(cache.with_suffix('.next.json'),cache)
                    old_plan=state.get('seed_plan')
                    state.update(status='unchanged',archive=state.get('archive',cfg['baseline_archive']),seed_plan=str(plan),
                                 last_success_slot=job['slot'],last_success_at=datetime.now(timezone.utc).isoformat(),pending=None,retry_after=0,error=None,needs_attention=False)
                    if full:state['last_full_hash']=time.time()
                    state['cleanup_pending']={'job':job,'plan':old_plan}
                    save(state_path,state)
                    cleanup_committed(cfg,state,job,previous_plan=old_plan)
                    state.pop('cleanup_pending');save(state_path,state)
                    return result
                job.update(phase='upload',build=result,full_hash=full);save(state_path,state)
            client=client or quark.Client(skill_dir=cfg.get('quark_skill'),session_input=cfg.get('authorized_request'),session_id=cfg.get('session_id'),workers=cfg.get('workers',4))
            result=None
            for attempt in range(3):
                try:
                    result=checkpoint(ticket,archive,directory/'readback',client,tools);break
                except quark.TransferError as error:
                    if not error.retryable or attempt==2:raise
                    state.update(status='retrying',attempt=attempt+1,error='temporary_network');save(state_path,state)
                    time.sleep([30,120][attempt])
            if not result:raise RuntimeError('No verified checkpoint')
            # State promotion follows the cloud recovery record. Repeating this
            # phase after interruption is safe because the archive is immutable.
            if cache.with_suffix('.next.json').exists():os.replace(cache.with_suffix('.next.json'),cache)
            prior=state.get('archive');prior_plan=state.get('seed_plan')
            state.update(status='verified',archive=str(archive),snapshot=result['snapshot'],last_result=result,
                         seed_plan=str(directory/'private-plan.json'),last_success_slot=job['slot'],
                         last_success_at=datetime.now(timezone.utc).isoformat(),pending=None,retry_after=0,error=None,needs_attention=False)
            if job.get('full_hash'):state['last_full_hash']=time.time()
            state['cleanup_pending']={'job':job,'archive':prior,'plan':prior_plan}
            save(state_path,state)
            receipt={'status':'verified',**result,'archive':str(archive),'build':job.get('build'),
                     'previous_archive':prior,'verified_at':state['last_success_at']}
            save(directory/'receipt.json',receipt)
            cleanup_committed(cfg,state,job,prior,prior_plan)
            state.pop('cleanup_pending');save(state_path,state)
            return receipt
        except Exception as error:
            state.update(status='failed',error=error_kind(error),retry_after=time.time()+3600,
                         needs_attention=isinstance(error,ValueError) or isinstance(error,quark.TransferError) and not error.retryable,
                         failed_at=datetime.now(timezone.utc).isoformat())
            save(state_path,state)
            raise


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--force',action='store_true')
    p.add_argument('--session-input');p.add_argument('--session-id');p.add_argument('--list-versions',action='store_true');a=p.parse_args()
    cfg=cloud.local_only(a.config);log=cfg.with_name('automatic-run.log')
    settings=private.read(cfg)
    if a.list_versions:
        print(json.dumps(versions(settings['recovery']),ensure_ascii=False));return
    client=quark.Client(skill_dir=settings.get('quark_skill'),session_input=a.session_input or settings.get('authorized_request'),
                        session_id=a.session_id or settings.get('session_id'),workers=settings.get('workers',4))
    try:
        with log.open('a',encoding='utf8',buffering=1) as stream,redirect_stdout(stream):result=run(cfg,a.force,client)
        result['notices']=getattr(client,'notices',[])
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        if str(error)=='backup_already_running':
            print(json.dumps({'status':'already_running'}));return
        print(json.dumps({'status':'failed','reason':error_kind(error),'detail_type':type(error).__name__,
                          'notices':getattr(client,'notices',[]),
                          'action':'Inspect the private local run log and state; current verified recovery remains available'},ensure_ascii=False))
        raise SystemExit(1)

if __name__=='__main__':main()

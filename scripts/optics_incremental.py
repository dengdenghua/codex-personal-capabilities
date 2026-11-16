"""Local-only complete checkpoints, reusing unchanged compressed ZIP objects.

Each output remains a standalone optics-private-backup-v1 archive. Only encrypted
restic objects are eligible for transport. No delta chain is needed to restore.
"""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import zipfile

import optics_private as private
import optics_cloud as cloud


def permitted(path):
    path=Path(path)
    if any(word in path.stem.lower() for word in ['password','credential','secret','token','cookie','密码','密钥','凭据','口令']):return False
    if path.suffix.lower() in {'.lic','.license','.kdbx','.keychain','.p12','.p8','.ppk'}:return False
    return private.allowed(path) and path.name.lower() not in {
        'password.key','recovery.json','previous-recovery.json','next-recovery.json',
        'rclone.conf','cloud-profile.json','automatic-backup.json','config.json',
        'tokens.json','token.json','secrets.json','login.json','cookies.json'} and not path.name.lower().startswith('recovery-')


def stamp(path):
    s=path.stat()
    return [s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_dev,s.st_ino]


def refresh_plan(seed_path,output,extra_roots=()):
    """Refresh managed libraries and indexed originals, never scan whole work drives."""
    seed=private.read(seed_path)
    excluded=[i for i in seed['files'] if not permitted(i['source'])]
    entries={i['target']:dict(i) for i in seed['files'] if permitted(i['source'])}
    source_paths={os.path.normcase(os.path.abspath(i['source'])) for i in entries.values()}
    cfg_source=next((i['source'] for i in seed['files'] if i['target']=='workbench/config.original.json'),None)
    cfg=dict(seed['workbench_config'])
    if cfg_source:
        raw=private.read(cfg_source)
        cfg.update({k:v for k,v in raw.items() if k in private.PRIVATE_CONFIG_KEYS})
        for key in ['coverage_file','data_dir','skill_dir']:
            if key in cfg:cfg[key]=str(private.local_path(Path(cfg_source).parent,cfg[key]))
    def add(path,target,expected=None,aliases=()):
        path=Path(path).resolve()
        if not permitted(path):return
        if target.startswith('new-materials/') and os.path.normcase(str(path)) in source_paths:return
        cloud.reject_link(path)
        private.safe_relative(target)
        entries[target]={'source':str(path),'target':target,'aliases':list(dict.fromkeys([str(path),*aliases])),
                         'expected_sha256':expected,'bytes':path.stat().st_size}
        source_paths.add(os.path.normcase(str(path)))
    def tree(root,prefix,databases=False):
        root=Path(root).resolve()
        cloud.reject_link(root)
        if not root.is_dir():raise FileNotFoundError('Required knowledge directory is unavailable')
        for base,dirs,names in os.walk(root):
            dirs[:]=[d for d in dirs if d not in private.BLOCKED and not Path(base,d).is_symlink()]
            for d in dirs:cloud.reject_link(Path(base,d))
            for name in names:
                path=Path(base,name)
                if permitted(path) and (not databases or path.suffix in {'.sqlite','.sqlite3','.db'}):
                    add(path,prefix+'/'+path.relative_to(root).as_posix())
    if cfg.get('data_dir'):tree(cfg['data_dir'],'workbench/data',True)
    if cfg.get('skill_dir'):tree(cfg['skill_dir'],'private-skill')
    lens_entry=next((i for i in seed['files'] if i['target']=='lens/lens_library.sqlite'),None)
    if lens_entry:tree(Path(lens_entry['source']).parent,'lens')
    for index,root in enumerate(extra_roots):tree(root,'new-materials/root-'+str(index))
    for key in ['knowledge_catalogs','pending_knowledge_catalogs']:
        for catalog in cfg.get(key,[]):
            for field in ['catalog','audit']:
                if field in catalog:
                    path=private.local_path(Path(cfg_source).parent,catalog[field]);catalog[field]=str(path)
                    add(path,'catalogs/'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'/'+path.name)
    missing=list(seed['missing'])
    for i in excluded:
        if i.get('expected_sha256') and not any(m['sha256']==i['expected_sha256'] for m in missing):
            missing.append({'id':i['expected_sha256'],'sha256':i['expected_sha256'],'bytes':i['bytes'],
                            'paths':i['aliases'],'reason':'excluded_sensitive_filename'})
    known={i.get('expected_sha256') for i in entries.values()}|{m['sha256'] for m in missing if m.get('reason')=='excluded_sensitive_filename'}
    requests=[(m['sha256'],m['bytes'],m['paths']) for m in missing if m.get('reason')!='excluded_sensitive_filename']
    if cfg.get('coverage_file'):
        add(cfg['coverage_file'],'workbench/coverage.json')
        for row in private.read(cfg['coverage_file']):
            requests.append((row['sha256'],row['bytes'],[x['path'] for x in row['files']]))
    dbpath=Path(cfg.get('data_dir',''))/'workbench.sqlite3'
    if dbpath.is_file():
        with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
            for identity,paths,size in db.execute('SELECT id,paths,bytes FROM documents'):
                requests.append((identity,size,json.loads(paths)))
    if lens_entry:
        path=Path(lens_entry['source'])
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            locations={}
            for identity,value in db.execute('SELECT source_id,original_path FROM locations'):locations.setdefault(identity,[]).append(value)
            for identity,digest,path,size in db.execute('SELECT id,sha256,local_path,bytes FROM sources'):
                requests.append((digest,size,([path] if path else [])+locations.get(identity,[])))
    memory=next((i['source'] for i in entries.values() if i['target']=='workflow-memory/memory.sqlite3'),None)
    if memory:
        with closing(sqlite3.connect(Path(memory).as_uri()+'?mode=ro',uri=True)) as db:
            for (payload,) in db.execute('SELECT payload FROM entries'):
                for value in json.loads(payload).get('artifacts',[]):
                    if value.get('sha256') and value.get('path'):requests.append((value['sha256'],None,[value['path']]))
    for digest,size,paths in requests:
        if digest in known:continue
        known.add(digest)
        match=next((Path(p) for p in paths if Path(p).is_file() and permitted(p) and private.sha(p)==digest),None)
        if match:
            add(match,'evidence/added/'+digest+'/'+match.name,digest,paths)
            missing=[m for m in missing if m['sha256']!=digest]
        else:
            if not any(m['sha256']==digest for m in missing):missing.append({'id':digest,'sha256':digest,'bytes':size,'paths':paths})
            # A memory may reference an older revision of a still-existing file.
            # Keep that missing identity explicit, but also protect today's bytes.
            for value in paths:
                path=Path(value)
                if path.is_file() and permitted(path):
                    add(path,'evidence/current/'+hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]+'/'+path.name)
    result={'format':'optics-private-plan-v1','workbench_config':cfg,'files':list(entries.values()),'missing':missing,'complete':not missing}
    private.write(cloud.local_only(output),result)
    return result


def copy_compressed(old,new,member):
    """Copy a trusted, seekable ZIP64 member without recompressing its payload."""
    info=old.getinfo(member)
    if info.flag_bits & 9 or info.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}:
        raise ValueError('Unsupported ZIP member flags or compression')
    old.fp.seek(info.header_offset)
    header=old.fp.read(30)
    if len(header)!=30 or header[:4]!=b'PK\x03\x04':raise ValueError('Invalid local ZIP header')
    name_len,extra_len=struct.unpack_from('<HH',header,26)
    new.fp.seek(new.start_dir);offset=new.fp.tell();new.fp.write(header)
    remaining=name_len+extra_len+info.compress_size
    while remaining:
        block=old.fp.read(min(1024*1024,remaining))
        if not block:raise ValueError('Truncated compressed object')
        new.fp.write(block);remaining-=len(block)
    cloned=copy.copy(info);cloned.header_offset=offset
    new.filelist.append(cloned);new.NameToInfo[member]=cloned
    new.start_dir=new.fp.tell();new._didModify=True


def build(plan_path,baseline,output,cache_path,full_hash=False):
    plan=private.read(plan_path);baseline=cloud.local_only(baseline);output=cloud.local_only(output)
    cache_path=cloud.local_only(cache_path);cloud.reject_link(baseline);cloud.reject_link(output)
    checksum=private.read(baseline.with_suffix(baseline.suffix+'.sha256.json'))['sha256']
    if private.sha(baseline)!=checksum:raise ValueError('Baseline archive checksum mismatch')
    before=stamp(baseline)
    if output.exists() or output.with_suffix('.partial').exists():raise FileExistsError('Checkpoint output already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    cache=private.read(cache_path) if cache_path.exists() else {}
    next_cache={};reused=0;written=0;records=[];payloads={};retained_missing=[]
    with zipfile.ZipFile(baseline) as old,tempfile.TemporaryDirectory(prefix='sqlite-',dir=output.parent) as temporary:
        previous=json.loads(old.read('manifest.json'));previous_by_target={i['target']:i for i in previous['files']}
        old_objects={n for n in old.namelist() if n.startswith('objects/')}
        def retain(record):
            if 'objects/'+record['sha256'] not in old_objects:raise ValueError('Missing historical object in baseline')
            records.append(record)
        for index,item in enumerate(plan['files']):
            private.safe_relative(item['target']);source=Path(item['source']);previous_record=previous_by_target.get(item['target'])
            if not permitted(source):raise ValueError('Credentials or recovery material in source plan')
            if not source.is_file():
                if previous_record:retain(previous_record);retained_missing.append(item['target']);continue
                raise FileNotFoundError('New source unavailable; current checkpoint unchanged')
            cloud.reject_link(source);signature=stamp(source);payload=source;counts=None
            with source.open('rb') as stream:is_db=stream.read(16)==b'SQLite format 3\x00'
            if is_db:
                payload=Path(temporary)/(str(index)+'.sqlite3');private.db_snapshot(source,payload);counts=private.database_counts(payload)
                digest=private.sha(payload)
            else:
                cached=cache.get(str(source))
                digest=cached['sha256'] if not full_hash and cached and cached['stamp']==signature else private.sha(source)
                if stamp(source)!=signature:raise ValueError('Source changed while scanning')
                next_cache[str(source)]={'stamp':signature,'sha256':digest}
            record={k:item[k] for k in ['target','aliases']};record.update(sha256=digest,bytes=payload.stat().st_size,sqlite_counts=counts)
            if item.get('expected_sha256') and digest!=item['expected_sha256']:
                if not previous_record or previous_record['sha256']!=item['expected_sha256']:
                    raise ValueError('Historical evidence identity changed without a verified fallback')
                retain(previous_record)
                record['target']='evidence/updated/'+digest+'/'+source.name
            records.append(record);payloads[digest]=(payload,stamp(payload))
            if index%2000==0:print('Incremental scan:',index,'/',len(plan['files']),flush=True)
        # Stable order makes unchanged compressed spans reusable by restic's chunker.
        unique={}
        for r in records:
            if r['target'] in unique and unique[r['target']]!=r:raise ValueError('Conflicting archive target')
            unique[r['target']]=r
        for r in previous['files']:
            if r['target'] not in unique and permitted(r['target']) and all(permitted(a) for a in r['aliases']):unique[r['target']]=r
        manifest={'format':'optics-private-backup-v1','complete':plan['complete'],'missing':plan['missing'],
                  'workbench_config':plan['workbench_config'],'files':list(unique.values())}
        if manifest==previous:
            private.write(cache_path.with_suffix('.next.json'),next_cache)
            return {'status':'unchanged','archive':str(baseline),'retained_missing_sources':len(retained_missing)}
        reserve=2*1024**3
        changed=sum(r['bytes'] for r in unique.values() if 'objects/'+r['sha256'] not in old_objects)
        if shutil.disk_usage(output.parent).free<baseline.stat().st_size+changed+reserve:
            raise OSError('Insufficient checkpoint staging space; keep existing verified version')
        partial=output.with_suffix('.partial');seen=set()
        with zipfile.ZipFile(partial,'x',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as new:
            for record in unique.values():
                digest=record['sha256'];member='objects/'+digest
                if member in seen:continue
                seen.add(member)
                if member in old_objects:copy_compressed(old,new,member);reused+=1
                else:
                    payload,signature=payloads[digest]
                    if stamp(payload)!=signature:raise ValueError('Source changed before archiving')
                    h=hashlib.sha256();size=0
                    with payload.open('rb') as src,new.open(member,'w',force_zip64=True) as dst:
                        for block in iter(lambda:src.read(1024*1024),b''):h.update(block);size+=len(block);dst.write(block)
                    if h.hexdigest()!=digest or size!=record['bytes'] or stamp(payload)!=signature:
                        raise ValueError('Source changed while archiving')
                    written+=1
            new.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        if stamp(baseline)!=before:raise ValueError('Baseline changed during incremental reuse')
        partial.rename(output)
        private.write(output.with_suffix(output.suffix+'.sha256.json'),{'sha256':private.sha(output),'archive':output.name})
        private.write(cache_path.with_suffix('.next.json'),next_cache)
        return {'status':'created','archive':str(output),'files':len(unique),'reused_objects':reused,'new_objects':written,
                'retained_missing_sources':len(retained_missing),'missing_originals':len(plan['missing'])}

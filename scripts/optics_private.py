"""Local-only optical backup/restore. Never invokes Git, network or source scripts."""
import argparse
from collections import defaultdict
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BLOCKED={'.git','__pycache__','.venv','venv','node_modules'}
PRIVATE_CONFIG_KEYS={'snapshot_note','coverage_file','data_dir','skill_dir','knowledge_catalogs','pending_knowledge_catalogs','startup_sync'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def source_name(path):return str(path).replace('\\','/').rsplit('/',1)[-1].lower()
def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def outside(path):
    p=Path(path).expanduser().resolve()
    if p==ROOT or p.is_relative_to(ROOT):raise ValueError('Private paths must be outside the public repository')
    # Other checkouts also must not receive a private archive or restoration.
    if any((q/'.git').exists() for q in [p,*p.parents]):raise ValueError('Private destination must not be in a Git checkout')
    return p
def allowed(p):
    return not (p.name.lower() in {'auth.json','credentials.json','config.toml','.env','server.log','server-error.log'} or p.name.lower().startswith('.env.') or p.suffix.lower() in {'.pem','.key','.pfx','.pyc'} or p.name.endswith(('-wal','-shm')))
def files(root):
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in BLOCKED and not Path(base,d).is_symlink()]
        for name in names:
            p=Path(base,name)
            if allowed(p) and not p.is_symlink():yield p
def local_path(base,value):
    p=Path(value).expanduser();return (p if p.is_absolute() else base/p).resolve()
def db_snapshot(source,dest):
    with closing(sqlite3.connect(Path(source).as_uri()+'?mode=ro',uri=True,timeout=30)) as src,closing(sqlite3.connect(dest)) as dst:
        src.backup(dst,pages=256,sleep=.01)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity check failed')
def database_counts(path):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t:db.execute('SELECT count(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}

def plan(config,lens,memory,search_roots,output):
    """Resolve indexed source identities; a filename match alone never selects a file."""
    config=Path(config).resolve();lens=Path(lens).resolve();memory=Path(memory).resolve()
    raw=read(config);cfg={k:v for k,v in raw.items() if k in PRIVATE_CONFIG_KEYS}
    for k in ['coverage_file','skill_dir','data_dir']:cfg[k]=str(local_path(config.parent,cfg[k]))
    roots=[Path(r).resolve() for r in search_roots]
    entries={};missing=[];hash_cache={};index=defaultdict(list)
    def digest(p):
        stat=p.stat();key=(str(p),stat.st_size,stat.st_mtime_ns)
        if key not in hash_cache:hash_cache[key]=sha(p)
        return hash_cache[key]
    def add(p,target,aliases=(),expected=None):
        p=Path(p).resolve()
        if not p.is_file() or not allowed(p):raise ValueError('Missing or excluded required private file')
        key=str(p)
        if key not in entries:entries[key]={'source':key,'target':target,'aliases':[key],'expected_sha256':expected,'bytes':p.stat().st_size}
        item=entries[key]
        item['aliases']=list(dict.fromkeys([*item['aliases'],*map(str,aliases)]))
        if expected:
            if item['expected_sha256'] and item['expected_sha256']!=expected:raise ValueError('Conflicting evidence identity')
            item['expected_sha256']=expected
        return item
    add(config,'workbench/config.original.json')
    add(cfg['coverage_file'],'workbench/coverage.json')
    for p in files(cfg['data_dir']):
        if p.suffix in {'.sqlite','.sqlite3','.db'}:add(p,'workbench/data/'+p.name)
    for p in files(cfg['skill_dir']):add(p,'private-skill/'+p.relative_to(cfg['skill_dir']).as_posix())
    for p in files(lens):add(p,'lens/'+p.relative_to(lens).as_posix())
    add(memory,'workflow-memory/memory.sqlite3')
    for key in ['knowledge_catalogs','pending_knowledge_catalogs']:
        for item in cfg.get(key,[]):
            for field in ['catalog','audit']:
                if field in item:
                    p=local_path(config.parent,item[field]);item[field]=str(p)
                    add(p,'catalogs/'+hashlib.sha256(str(p).encode()).hexdigest()[:16]+'/'+p.name)
    print('Indexing explicitly selected search roots',flush=True)
    for i,root in enumerate(roots):
        for p in files(root):
            try:index[(p.name.lower(),p.stat().st_size)].append(p)
            except OSError:continue
    def evidence(identifier,expected,size,aliases):
        aliases=list(dict.fromkeys(aliases));candidates=[Path(a) for a in aliases if Path(a).is_file()]
        for a in aliases:candidates.extend(index.get((source_name(a),size),[]))
        match=next((p for p in dict.fromkeys(candidates) if p.stat().st_size==size and digest(p)==expected),None)
        if match:
            target='evidence/'+expected+'/'+match.name
            for i,root in enumerate(roots):
                if match.is_relative_to(root):target=f'evidence/root-{i}/'+match.relative_to(root).as_posix();break
            add(match,target,aliases,expected)
        else:missing.append({'id':identifier,'sha256':expected,'bytes':size,'paths':aliases})
    coverage=read(cfg['coverage_file'])
    for n,g in enumerate(coverage):
        evidence(g['sha256'],g['sha256'],g['bytes'],[f['path'] for f in g['files']])
        if n%1000==0:print('Verified coverage identities:',n,flush=True)
    with closing(sqlite3.connect((lens/'lens_library.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        locations=defaultdict(list)
        for identity,path in db.execute('SELECT source_id,original_path FROM locations'):locations[identity].append(path)
        for n,(identity,digest_value,path,size) in enumerate(db.execute('SELECT id,sha256,local_path,bytes FROM sources')):
            aliases=[path] if path else []
            aliases.extend(locations[identity])
            evidence(identity,digest_value,size,aliases)
            if n%2000==0:print('Verified lens identities:',n,flush=True)
    result={'format':'optics-private-plan-v1','workbench_config':cfg,'files':list(entries.values()),'missing':missing,'complete':not missing}
    write(outside(output),result)
    print('Plan:',len(entries),'files;',len(missing),'missing identities;',round(sum(x['bytes'] for x in entries.values())/2**30,2),'GiB',flush=True)
    return augment(output)

def augment(plan_path):
    """Include saved document additions and explicit offline-memory artifact links."""
    data=read(plan_path);entries={i['source']:i for i in data['files']};known={i.get('expected_sha256') for i in data['files']}|{i['sha256'] for i in data['missing']}
    requests=[]
    dbpath=Path(data['workbench_config']['data_dir'])/'workbench.sqlite3'
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        for identity,paths,size in db.execute('SELECT id,paths,bytes FROM documents'):
            if identity not in known:requests.append({'id':identity,'sha256':identity,'paths':json.loads(paths),'bytes':size})
    memory=next(i['source'] for i in data['files'] if i['target']=='workflow-memory/memory.sqlite3')
    with closing(sqlite3.connect(Path(memory).as_uri()+'?mode=ro',uri=True)) as db:
        for (payload,) in db.execute('SELECT payload FROM entries'):
            for a in json.loads(payload).get('artifacts',[]):
                if a.get('sha256') and a.get('path'):requests.append({'id':a['sha256'],'sha256':a['sha256'],'paths':[a['path']],'bytes':None})
    for item in requests:
        digest=item['sha256'];matching=next((e for e in entries.values() if e.get('expected_sha256')==digest),None)
        if matching:
            matching['aliases']=list(dict.fromkeys(matching['aliases']+item['paths']));continue
        if any(m['sha256']==digest for m in data['missing']):continue
        match=next((Path(p).resolve() for p in item['paths'] if Path(p).is_file() and allowed(Path(p)) and sha(p)==digest),None)
        if match:
            key=str(match)
            if key not in entries:entries[key]={'source':key,'target':'evidence/memory-artifacts/'+digest+'/'+match.name,'aliases':[],'expected_sha256':digest,'bytes':match.stat().st_size}
            entries[key]['expected_sha256']=digest
            entries[key]['aliases']=list(dict.fromkeys(entries[key]['aliases']+[key]+item['paths']))
        else:data['missing'].append(item)
    data.update(files=list(entries.values()),complete=not data['missing']);write(outside(plan_path),data)
    print('Including saved documents and memory artifacts:',len(data['files']),'files;',len(data['missing']),'unresolved identities',flush=True)
    return data

def backup(plan_path,archive):
    data=read(plan_path);archive=outside(archive)
    if archive.exists():raise FileExistsError('Backup already exists; choose a new checkpoint')
    archive.parent.mkdir(parents=True,exist_ok=True)
    manifest={'format':'optics-private-backup-v1','complete':data['complete'],'missing':data['missing'],'workbench_config':data['workbench_config'],'files':[]}
    partial=archive.with_suffix(archive.suffix+'.partial')
    if partial.exists():raise FileExistsError('Partial backup exists; retain it for diagnosis or choose another path')
    seen=set()
    with tempfile.TemporaryDirectory(prefix='optics-snapshot-',dir=archive.parent) as temp,zipfile.ZipFile(partial,'x',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for n,item in enumerate(data['files']):
            p=Path(item['source']);payload=p;counts=None
            with p.open('rb') as f:is_db=f.read(16)==b'SQLite format 3\x00'
            if is_db:
                payload=Path(temp)/'snapshot.sqlite3';db_snapshot(p,payload);counts=database_counts(payload)
            digest=sha(payload)
            if item.get('expected_sha256') and digest!=item['expected_sha256']:raise ValueError('Source identity changed since plan; backup stopped')
            record={k:item[k] for k in ['target','aliases']};record.update(sha256=digest,bytes=payload.stat().st_size,sqlite_counts=counts)
            member='objects/'+digest
            if member not in seen:
                # Stream through ZIP64 and check the exact bytes written, not only a pre-read.
                h=hashlib.sha256();size=0
                with payload.open('rb') as src,z.open(member,'w',force_zip64=True) as out:
                    for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);size+=len(chunk);out.write(chunk)
                if h.hexdigest()!=digest or size!=record['bytes']:raise ValueError('Source changed while archiving')
                seen.add(member)
            manifest['files'].append(record)
            if n%500==0:print('Archived',n,'/',len(data['files']),flush=True)
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
    partial.rename(archive)
    digest=sha(archive);write(archive.with_suffix(archive.suffix+'.sha256.json'),{'sha256':digest,'archive':archive.name})
    print('Backup saved;',len(manifest['files']),'paths;',len(seen),'unique objects; complete=',manifest['complete'],flush=True)
    return manifest

def rescan(plan_path,roots):
    data=read(plan_path);index=defaultdict(list);wanted={source_name(p) for m in data['missing'] for p in m['paths']}
    for n,root in enumerate(map(Path,roots)):
        for p in files(root):
            if p.name.lower() in wanted:
                index[(p.name.lower(),p.stat().st_size)].append(p.resolve())
        print('Scanned recovery root',n,flush=True)
    entries={x['source']:x for x in data['files']};unresolved=[];cache={}
    for item in data['missing']:
        candidates=[]
        for alias in item['paths']:
            name=source_name(alias)
            if item['bytes'] is None:
                for (candidate_name,_),values in index.items():
                    if candidate_name==name:candidates.extend(values)
            else:candidates.extend(index.get((name,item['bytes']),[]))
        found=None
        for p in candidates:
            if str(p) not in cache:cache[str(p)]=sha(p)
            if cache[str(p)]==item['sha256']:found=p;break
        if not found:unresolved.append(item);continue
        p=found;target='evidence/recovered/'+item['sha256']+'/'+p.name;key=str(p)
        if key not in entries:entries[key]={'source':key,'target':target,'aliases':[key],'expected_sha256':item['sha256'],'bytes':p.stat().st_size}
        entries[key]['expected_sha256']=item['sha256']
        entries[key]['aliases']=list(dict.fromkeys(entries[key]['aliases']+item['paths']))
    data.update(files=list(entries.values()),missing=unresolved,complete=not unresolved)
    write(outside(plan_path),data);print('Remaining missing identities:',len(unresolved),flush=True)
    return data

def safe_relative(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or not name:raise ValueError('Unsafe backup path')
    return p

def restore(archive,destination,allow_incomplete=False):
    archive=Path(archive).resolve();destination=outside(destination)
    if destination.exists():raise FileExistsError('Restore into a NEW directory; existing data is never overwritten')
    checksum=read(archive.with_suffix(archive.suffix+'.sha256.json'))
    if sha(archive)!=checksum['sha256']:raise ValueError('Backup archive checksum mismatch')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive members')
        for info in infos:
            safe_relative(info.filename)
            if ((info.external_attr>>16)&0o170000)==0o120000:raise ValueError('Symlink in archive')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('format')!='optics-private-backup-v1':raise ValueError('Unsupported backup format')
        if not manifest['complete'] and not allow_incomplete:raise ValueError('Backup has missing originals; review manifest before allowing partial recovery')
        total=sum(i['bytes'] for i in manifest['files'])
        destination.parent.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(destination.parent).free<total+256*1024*1024:raise OSError('Insufficient space for independent restored files')
        targets=set()
        for item in manifest['files']:
            target=str(safe_relative(item['target'])).casefold()
            if target in targets:raise ValueError('Duplicate restored target')
            targets.add(target)
            if not re.fullmatch('[0-9a-f]{64}',item['sha256']):raise ValueError('Invalid object hash')
            info=z.getinfo('objects/'+item['sha256'])
            if info.file_size!=item['bytes']:raise ValueError('Size mismatch')
        stage=destination.with_name(destination.name+'.restoring')
        stage.mkdir(exist_ok=False);mapping={};objects={}
        for n,item in enumerate(manifest['files']):
            target=stage/item['target'];target.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
            with z.open('objects/'+item['sha256']) as src,target.open('xb') as out:
                for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);out.write(chunk)
            if h.hexdigest()!=item['sha256']:raise ValueError('Restored object checksum mismatch')
            if item.get('sqlite_counts') is not None:
                with closing(sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Restored SQLite integrity failed')
                if database_counts(target)!=item['sqlite_counts']:raise ValueError('Restored SQLite row counts differ')
            actual=str(destination/item['target'])
            for alias in item['aliases']:mapping[alias]={'path':actual,'sha256':item['sha256']}
            objects[item['sha256']]={'path':actual,'sha256':item['sha256']}
            if n%500==0:print('Restored',n,'/',len(manifest['files']),flush=True)
        cfg=manifest['workbench_config']
        for key in ['knowledge_catalogs','pending_knowledge_catalogs']:
            for entry in cfg.get(key,[]):
                for field in ['catalog','audit']:
                    if field in entry:entry[field]=mapping[entry[field]]['path']
        cfg.update(data_dir=str(destination/'workbench/data'),coverage_file=str(destination/'workbench/coverage.json'),skill_dir=str(destination/'private-skill'),startup_sync=False,
                   lens_library_root=str(destination/'lens'),workflow_memory=str(destination/'workflow-memory/memory.sqlite3'),path_map=str(destination/'path-map.json'),restore_report=str(destination/'restore-report.json'))
        write(stage/'workbench/config.json',cfg)
        write(stage/'path-map.json',{'paths':mapping,'objects':objects})
        write(stage/'restore-report.json',{'complete':manifest['complete'],'missing':manifest['missing'],'files_verified':len(manifest['files']),'archive_sha256':checksum['sha256']})
        stage.rename(destination)
    print('Restore verified:',len(manifest['files']),'files; original provenance unchanged',flush=True)
    return destination

def activate(destination,runtime_config,codex_home=None,allow_incomplete=False):
    destination=outside(destination);runtime_config=outside(runtime_config);home=outside(codex_home or Path.home()/'.codex')
    report=read(destination/'restore-report.json')
    if not report['complete'] and not allow_incomplete:raise ValueError('Incomplete recovery requires explicit --allow-incomplete; review missing originals first')
    cfg=read(runtime_config);before=json.dumps(cfg,sort_keys=True);entry=cfg['servers']['optics_workbench']
    env=entry.setdefault('env',{});env['OPTICS_WORKBENCH_CONFIG']=str(destination/'workbench/config.json');env['OPTICS_WORKBENCH_DATA']=str(destination/'workbench/data')
    if json.dumps(cfg,sort_keys=True)!=before:
        if runtime_config.exists():shutil.copyfile(runtime_config,runtime_config.with_suffix('.previous.json'))
        write(runtime_config,cfg)
    for name,settings in [('lens-toolkit.local.json',{'library_root':str(destination/'lens'),'path_map':str(destination/'path-map.json')}),('optical-workflow-memory.local.json',{'store':str(destination/'workflow-memory/memory.sqlite3')})]:
        path=home/name
        old=read(path) if path.exists() else {};new={**old,**settings}
        if old!=new:
            if path.exists():shutil.copyfile(path,path.with_suffix('.previous.json'))
            write(path,new)
    print('Activated restored knowledge for subsequent MCP sessions')

def verify_restored(archive,destination,allow_incomplete=False):
    """Permit a retry only when the previous recovery exactly matches this archive."""
    archive=Path(archive);destination=outside(destination)
    expected=read(archive.with_suffix(archive.suffix+'.sha256.json'))['sha256']
    if sha(archive)!=expected:raise ValueError('Archive checksum mismatch')
    report=read(destination/'restore-report.json')
    if report['archive_sha256']!=expected or (not report['complete'] and not allow_incomplete):raise ValueError('Existing recovery belongs to a different or incomplete backup')
    with zipfile.ZipFile(archive) as z:
        for item in json.loads(z.read('manifest.json'))['files']:
            path=destination/str(safe_relative(item['target']))
            if not path.is_file() or sha(path)!=item['sha256']:raise ValueError('Existing recovery changed; keep it and use a new restore directory')
    print('Existing unchanged recovery verified; continuing installation')

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('plan');p.add_argument('--workbench-config',required=True);p.add_argument('--lens-root',required=True);p.add_argument('--memory',required=True);p.add_argument('--search-root',action='append',default=[]);p.add_argument('--output',required=True)
    p=sub.add_parser('backup');p.add_argument('--plan',required=True);p.add_argument('--archive',required=True)
    p=sub.add_parser('rescan');p.add_argument('--plan',required=True);p.add_argument('--search-root',action='append',required=True)
    p=sub.add_parser('augment');p.add_argument('--plan',required=True)
    p=sub.add_parser('restore');p.add_argument('--archive',required=True);p.add_argument('--destination',required=True);p.add_argument('--allow-incomplete',action='store_true')
    p=sub.add_parser('activate');p.add_argument('--destination',required=True);p.add_argument('--runtime-config',required=True);p.add_argument('--codex-home');p.add_argument('--allow-incomplete',action='store_true')
    a=parser.parse_args()
    if a.action=='plan':plan(a.workbench_config,a.lens_root,a.memory,a.search_root,a.output)
    elif a.action=='backup':backup(a.plan,a.archive)
    elif a.action=='rescan':rescan(a.plan,a.search_root)
    elif a.action=='augment':augment(a.plan)
    elif a.action=='restore':restore(a.archive,a.destination,a.allow_incomplete)
    else:activate(a.destination,a.runtime_config,a.codex_home,a.allow_incomplete)
if __name__=='__main__':main()

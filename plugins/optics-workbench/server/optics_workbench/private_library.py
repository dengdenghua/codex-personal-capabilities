"""Read-only restored evidence access. Source identity/provenance are never rewritten."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from . import lens_library

def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def status(wb):
    result={'lens_configured':False,'workflow_memory_configured':False,'path_map_configured':False}
    root=wb.config.get('lens_library_root')
    if root:
        with closing(lens_library.connect(Path(root))) as db:
            result['lens_sources']=db.execute('SELECT count(*) FROM sources').fetchone()[0]
            result['lens_cases']=db.execute('SELECT count(*) FROM cases').fetchone()[0]
        result['lens_configured']=True
    memory=wb.config.get('workflow_memory')
    if memory:
        with closing(sqlite3.connect(Path(memory).as_uri()+'?mode=ro',uri=True)) as db:result['workflow_entries']=db.execute('SELECT count(*) FROM entries').fetchone()[0]
        result['workflow_memory_configured']=True
    mapping=wb.config.get('path_map')
    if mapping:result['path_map_configured']=Path(mapping).is_file()
    report=wb.config.get('restore_report')
    if report:
        restored=load(report);result.update(restoration_complete=restored['complete'],missing_original_identities=len(restored['missing']))
    return result

def lens(wb,kind,query='',limit=10,identifier=None):
    root=wb.config.get('lens_library_root')
    if not root:raise ValueError('Private lens library is not configured')
    with closing(lens_library.connect(Path(root))) as db:
        return lens_library.detail(db,kind,identifier) if identifier is not None else lens_library.search(db,kind,query,limit)

def workflow_memory(wb,query='',limit=10):
    path=wb.config.get('workflow_memory')
    if not path:raise ValueError('Private workflow memory is not configured')
    if not 1<=limit<=50:raise ValueError('limit must be 1..50')
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        terms=query.split();where=' AND '.join('(instr(text,?)>0 OR instr(scope,?)>0)' for _ in terms) or '1'
        rows=db.execute('SELECT id,payload FROM entries WHERE '+where+' ORDER BY recorded_at DESC LIMIT ?',[t for term in terms for t in (term,term)]+[limit]).fetchall()
    return {'graph_sync':'not_performed','entries':[{'id':key,**json.loads(payload)} for key,payload in rows]}

def resolve(wb,identity):
    config=wb.config.get('path_map')
    if not config:raise ValueError('Restored path mapping is not configured')
    mapping=load(config);entry=mapping.get('objects',{}).get(identity) or mapping.get('paths',{}).get(identity)
    if not entry:
        report=wb.config.get('restore_report')
        if report and any(x['sha256']==identity or identity in x['paths'] for x in load(report)['missing']):raise ValueError('Source is indexed but its original file is missing from this backup')
        raise ValueError('Source is not registered in restored mapping')
    p=Path(entry['path']);digest=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!=entry['sha256']:raise ValueError('Restored source identity changed')
    return {'path':str(p),'sha256':entry['sha256'],'verified':True,'source_modified':False,'native_validation':'not_performed'}

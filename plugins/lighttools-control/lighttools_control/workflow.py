"""Bounded receiver workflows. No hidden tracing, model replacement or file pruning."""
import csv
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone
import psutil

POSE = ('X', 'Y', 'Z', 'ALPHA', 'BETA', 'GAMMA')
FLAGS = ('ENABLED', 'SAVE RAY DATA', 'COLLECTRAYPATHS', 'SHOWRAYPATHS')
RAY_FIELDS = ('RAYDATAX','RAYDATAY','RAYDATAZ','RAYDATAENTERINGL',
              'RAYDATAENTERINGM','RAYDATAENTERINGN','RAYDATAMAGNITUDE',
              'RAYDATAWAVELENGTH','RAYDATAORDINALNUMBER','RAYDATAPASSFILTERS')

def resources(path, pid=None):
    p = Path(path)
    if not p.is_absolute():
        raise ValueError('Resource path must be absolute')
    p = p.resolve()
    while not p.exists():
        p = p.parent
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(p))
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'disk_path': str(p), 'disk_free_bytes': disk.free,
              'ram_available_bytes': vm.available, 'ram_total_bytes': vm.total,
              'vram_measured': False}
    if pid is not None:
        proc = psutil.Process(pid)
        mem = proc.memory_info()
        result['process'] = {'pid': pid, 'created': proc.create_time(), 'name': proc.name(),
                             'working_set_bytes': mem.rss,
                             'private_bytes': getattr(mem, 'private', None)}
    return result

def require_capacity(snapshot, min_free_ram_bytes=0, required_disk_bytes=0):
    for v in (min_free_ram_bytes, required_disk_bytes):
        if type(v) is not int or v < 0:
            raise ValueError('Capacity thresholds must be nonnegative integer bytes')
    if snapshot['ram_available_bytes'] < min_free_ram_bytes:
        raise RuntimeError('Insufficient available RAM for the requested reserve; no operation started')
    if snapshot['disk_free_bytes'] < required_disk_bytes:
        raise RuntimeError('Insufficient free disk space for the requested reserve; no operation started')

def receiver_inventory(s):
    rr = s.objects('LENS_MANAGER[1]', 'RECEIVER', 500)
    if rr['truncated']:
        raise ValueError('Receiver inventory exceeds 500; no partial configuration is allowed')
    rows = []
    for r in rr['objects']:
        ff = s.objects(r['key'], 'FORWARD_SIM_FUNCTION', 2)
        if ff['truncated'] or len(ff['objects']) != 1:
            raise ValueError('Expected one forward function per receiver')
        f = ff['objects'][0]['key']
        rows.append({**r, 'function': f, 'pose': {k:s.get(r['key'],k) for k in POSE},
                     'solid':s.get(r['key'],'SOLID NAME'),
                     'surface':s.get(r['key'],'SURFACE NAME'),
                     'settings':{k:s.get(f,k) for k in FLAGS}})
    return {'count':len(rows), 'enabled_count':sum(r['settings']['ENABLED']=='Yes' for r in rows),
            'units':s.get('LENS_MANAGER[1]','UNITS'), 'receivers':rows}

def selected_receivers(inventory, names, maximum):
    if type(maximum) is not int or not 1 <= maximum <= 16:
        raise ValueError('max_enabled must be 1..16; raise only for an explicitly justified batch')
    if not names or len(names)>maximum or len(set(names))!=len(names):
        raise ValueError('Provide distinct receiver names within max_enabled')
    selected=[]
    for name in names:
        matches=[r for r in inventory['receivers'] if r['name']==name]
        if len(matches)!=1:
            raise ValueError(f'Receiver name missing or ambiguous: {name}')
        selected.append(matches[0])
    return selected

def configure_receivers(s, names, max_enabled=2, save_rays=True, collect_paths=False, mark=None):
    before=receiver_inventory(s)
    selected=selected_receivers(before,names,max_enabled)
    keys={r['key'] for r in selected}
    writes=[]
    for r in before['receivers']:
        yes=r['key'] in keys
        desired={'ENABLED':'Yes' if yes else 'No','SAVE RAY DATA':'Yes' if yes and save_rays else 'No',
                 'COLLECTRAYPATHS':'Yes' if yes and collect_paths else 'No','SHOWRAYPATHS':'No'}
        for field,value in desired.items():
            writes.append((r['function'],field,value,r['settings'][field]))
        if yes:
            writes.append((r['function'],'RAYINFOTOUSE','Incident',s.get(r['function'],'RAYINFOTOUSE')))
    if mark:mark(before=before)
    s.cmd('DBUpdateOff')
    try:
        for key,field,value,old in writes:
            if old!=value:s.status('DbSet',key,field,value)
    finally:
        s.cmd('DBUpdateOn')
    mismatches=[]
    for key,field,value,_ in writes:
        actual=s.get(key,field)
        if actual!=value:mismatches.append({'key':key,'field':field,'expected':value,'actual':actual})
    if mismatches:
        raise RuntimeError('Receiver readback mismatch; partial changes remain: '+json.dumps(mismatches))
    return {'before':before,'after':receiver_inventory(s),'global_simulation_path_settings_changed':False,
            'saved_ray_cache_cleared':False}

def validate_receiver_planes(s, checks, expected_units='Millimeters', tolerance_mm=1e-6):
    if not 1<=len(checks)<=16 or not math.isfinite(tolerance_mm) or tolerance_mm<=0:
        raise ValueError('Require 1..16 plane checks and a positive finite tolerance')
    inv=receiver_inventory(s)
    if inv['units']!=expected_units:raise ValueError('Model units differ from requested units')
    rows=[]
    for c in checks:
        r=selected_receivers(inv,[c['receiver_name']],1)[0]
        # These checks deliberately accept only dummy planes: spheres have a different origin contract.
        planes=s.objects('LENS_MANAGER[1]','PLANE_DUMMY_SURFACE',500)
        match=[p for p in planes['objects'] if p['name']==r['solid']]
        if planes['truncated'] or len(match)!=1:raise ValueError('Check requires an unambiguous dummy-plane attachment')
        key=match[0]['key'];actual={k:s.get(key,k) for k in POSE}
        expected=c['expected_pose']
        if set(expected)!=set(POSE) or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in expected.values()):
            raise ValueError('expected_pose must give six finite XYZ/ALPHA/BETA/GAMMA fields')
        # Conservative exact Euler convention; alternative equivalent triples require explicit review.
        pose_ok=all(abs(actual[k]-expected[k])<=tolerance_mm for k in 'XYZ') and all(abs((actual[k]-expected[k]+180)%360-180)<=1e-7 for k in POSE[3:])
        attached=all(abs(actual[k]-r['pose'][k])<=1e-7 for k in POSE)
        width=s.get(key,'WIDTH');height=s.get(key,'HEIGHT')
        min_width=c.get('min_width',0);min_height=c.get('min_height',0)
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in (min_width,min_height)):
            raise ValueError('Minimum dimensions must be finite nonnegative values')
        state={k:s.get(key,k) for k in ['CLIP BOUNDARY','RAYTRACEABLE']}
        defocus=s.get(r['key'],'DEFOCUS TYPE')
        rows.append({'receiver':r['name'],'plane_key':key,'expected':expected,'actual':actual,
                     'width':width,'height':height,**state,'defocus':defocus,
                     'verified':pose_ok and attached and width>=min_width and height>=min_height and state['RAYTRACEABLE']=='Yes' and defocus=='No Defocus'})
    return {'units':inv['units'],'verified':all(r['verified'] for r in rows),'checks':rows,
            'scope':'Matches caller-specified planes; does not infer optical correctness or microfacet reference height.'}

def trace_preflight(s, simulation_key, expected_rays=None, max_enabled=2):
    inv=receiver_inventory(s)
    enabled=[r for r in inv['receivers'] if r['settings']['ENABLED']=='Yes']
    selected_receivers(inv,[r['name'] for r in enabled],max_enabled)
    src=s.objects('LENS_MANAGER[1]','SOURCE',5000)
    if src['truncated']:raise ValueError('Source inventory incomplete')
    source_count=sum(s.get(r['key'],'ENABLED')=='Yes' for r in src['objects'])
    if not source_count:raise ValueError('No enabled source')
    if expected_rays is not None:
        if type(expected_rays) is not int or expected_rays<=0:raise ValueError('expected_rays must be a positive integer')
        if int(s.get(simulation_key,'MAXPROGRESS'))!=expected_rays:raise ValueError('Expected ray count differs from simulation target')
    return {'enabled_sources':source_count,'enabled_receivers':[r['name'] for r in enabled],
            'simulation_key':simulation_key,'expected_rays':expected_rays,
            'starting_seed':s.get(simulation_key,'STARTINGSEED')}

def trace_complete(s, preflight):
    n=int(s.get(preflight['simulation_key'],'REPORTED TOTAL RAYS TRACED'))
    expected=preflight['expected_rays']
    if n<=0 or (expected is not None and n!=expected):
        raise RuntimeError(f'Trace incomplete: reported {n}, expected {expected}; exclude from completed-run comparisons')
    return {**preflight,'reported_rays':n,'count_verified':expected is not None,
            'scope':'Selected forward simulation ray count only; inspect power closure and any other enabled simulations separately.'}

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def export_receiver_rays(s, receiver_name, simulation_key, output_path, chunk_rows=2000, max_records=10000000):
    if type(chunk_rows) is not int or not 1<=chunk_rows<=5000:raise ValueError('chunk_rows must be 1..5000')
    if type(max_records) is not int or not 0<=max_records<=10000000:raise ValueError('max_records must be 0..10000000')
    p=Path(output_path)
    if not p.is_absolute() or p.suffix.lower()!='.csv':raise ValueError('Use a new absolute .csv path')
    p=p.resolve();mp=p.with_suffix('.manifest.json')
    if p.exists() or mp.exists():raise FileExistsError('Output or manifest already exists')
    r=selected_receivers(receiver_inventory(s),[receiver_name],1)[0];f=r['function']
    nr=int(s.get(f,'NUMBEROFSAMPLES'));n=int(s.get(simulation_key,'REPORTED TOTAL RAYS TRACED'));seed=s.get(simulation_key,'STARTINGSEED')
    if not 0<nr<=max_records or n<=0:raise ValueError('No saved samples, invalid denominator, or record limit exceeded')
    snapshot=resources(str(p),s.pid)
    require_capacity(snapshot,required_disk_bytes=nr*len(RAY_FIELDS)*32+64*1024*1024)
    p.parent.mkdir(parents=True,exist_ok=True)
    manifest={'complete':False,'receiver':r,'simulation_key':simulation_key,'reported_source_rays':n,
              'seed':seed,'units':s.get('LENS_MANAGER[1]','UNITS'),'active_view':s.active_view(),
              'pid':s.pid,'fields':list(RAY_FIELDS),'coordinates':'local receiver surface; transform using saved pose',
              'normalization':'sum selected RAYDATAMAGNITUDE / reported_source_rays',
              'expected_records':nr,'written_records':0,'csv_path':str(p),'resources_before':snapshot}
    with mp.open('x',encoding='utf8') as stream:json.dump(manifest,stream,ensure_ascii=False,indent=2)
    try:
        with p.open('x',newline='',encoding='utf8') as stream:
            writer=csv.writer(stream);writer.writerow(RAY_FIELDS)
            for start in range(0,nr,chunk_rows):
                count=min(chunk_rows,nr-start)
                response=s.lt.GetReceiverRayData(f,list(RAY_FIELDS),[[0.]*len(RAY_FIELDS) for _ in range(count)],start,count)
                if response[0]!=0:raise RuntimeError(f'GetReceiverRayData status {response[0]}; export is incomplete')
                rows=response[1]
                if len(rows)!=count or any(len(row)!=len(RAY_FIELDS) or any(not math.isfinite(v) for v in row) for row in rows):raise RuntimeError('Invalid ray-data shape or nonfinite value')
                writer.writerows(rows);manifest['written_records']+=count
        if int(s.get(f,'NUMBEROFSAMPLES'))!=nr or int(s.get(simulation_key,'REPORTED TOTAL RAYS TRACED'))!=n or s.get(simulation_key,'STARTINGSEED')!=seed or s.active_view()!=manifest['active_view']:
            raise RuntimeError('Model or ray data changed during export')
        manifest.update(complete=True,sha256=sha256(p),bytes=p.stat().st_size)
    except Exception as exc:
        manifest['error']=str(exc)
        raise
    finally:
        with mp.open('w',encoding='utf8') as stream:json.dump(manifest,stream,ensure_ascii=False,indent=2)
    return {'manifest_path':str(mp),'csv_path':str(p),'records':nr,'sha256':manifest['sha256'],
            'complete':True,'cache_cleared':False,'note':'Exported cache remains; clear only after all required receivers have verified exports.'}

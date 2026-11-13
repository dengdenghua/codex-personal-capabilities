"""Flow diagnostics. Loading a DLL never constitutes solver-license validation."""
from pathlib import Path

from portable_paths import flow_home
class _FlowHome:
    def __truediv__(self, name): return flow_home()/name
BASE = _FlowHome()
LOAD_CODES = {0: 'loaded', 1: 'not_loaded', 2: 'already_loaded', 3: 'file_not_found',
              4: 'disabled', 5: 'conflict', 6: 'registration_error', 7: 'license_error', -1: 'unknown_error'}

def result_state(model,project,update=None):
    import hashlib,json,time
    from jobs import DATA,atomic
    from sw_connect import get_com_member as get
    identity=str(Path(get(model,'GetPathName')).resolve()).casefold()+'|'+str(get(project,'ProjectUUID'))
    folder=DATA/'flow-state';folder.mkdir(exist_ok=True)
    path=folder/(hashlib.sha256(identity.encode()).hexdigest()+'.json')
    if update is not None:
        atomic(path,{**update,'updated_at':time.time(),'identity':identity})
    return json.loads(path.read_text('utf-8')) if path.exists() else {'status':'untracked','note':'No tracked solve/setting change. Currentness is not established.'}

def preflight(sw, model, project_name):
    from sw_connect import get_com_member as get
    app = sw.GetAddInObject('FloWorks.App')
    if app is None: raise RuntimeError('Flow add-in is not loaded')
    doc = get(app, 'GetAPI').GetDocument(model)
    project = get(doc, 'IActiveProject') if doc is not None else None
    if project is None: raise RuntimeError('No active Flow project')
    actual = get(project, 'ProjectName')
    if actual != project_name: raise ValueError(f'Expected project {project_name!r}, found {actual!r}')
    path = Path(get(model, 'GetPathName'))
    if not path.is_absolute() or not path.is_file(): raise ValueError('Saved native document required')
    missing = []
    if int(get(model, 'GetType')) == 2:
        for component in model.GetComponents(False) or []:
            reference = get(component, 'GetPathName')
            if get(component, 'GetSuppression') != 0 and reference and not Path(reference).exists():
                missing.append(reference)
    settings = {}
    unavailable = {}
    for key in ('ProjectUUID', 'HeatTransfer', 'Radiation', 'AutomaticMeshDefinition'):
        try: settings[key] = get(project, key)
        except Exception as exc: unavailable[key] = str(exc)
    return {'document': str(path), 'project': actual, 'settings': settings,
            'unavailable_settings': unavailable, 'missing_active_references': missing,
            'unsaved_model_changes': bool(get(model, 'GetSaveFlag')),
            'note': 'Structural preflight only. Does not validate physical inputs, mesh independence, or licenses.'}

def parameters(sw, model, project_name):
    """Read actual feature identities and parameter units before any parameter edit."""
    from sw_connect import get_com_member as get
    check=preflight(sw,model,project_name)
    project=get(get(sw.GetAddInObject('FloWorks.App'),'GetAPI').GetDocument(model),'IActiveProject')
    features=[]
    entries=[(f,None) for f in get(project,'EnumFeatures') or []]
    entries.append((get(project,'GlobalMeshSettings'),'@global_mesh'))
    for feature,alias in entries:
        row={'name':'Global mesh' if alias else get(feature,'Name_'),'uuid':alias or get(feature,'UUID_'),'type':140 if alias else get(feature,'Type_'),'parameters':[]}
        if row['type']==21:row['material_path']=get(feature,'GetPathToSolidMaterial')
        try:row['references']=get(feature,'GetReferencesNames')
        except Exception as exc:row['references_error']=str(exc)
        try:ids=[1181,1182] if alias else feature.GetOrderParametersArray()
        except AttributeError:ids=[]
        for key in ids or []:
            item={'id':key}
            try:
                param=feature.GetParameter(key,'')
                for field in ['value','UnitID','Type','DependenceType','Formula']:
                    item[field]=get(param,field)
                item['display_unit']=project.GetUnitShortName(item['UnitID'])
            except Exception as exc:item['error']=str(exc)
            row['parameters'].append(item)
        features.append(row)
    return {'preflight':check,'features':features,
            'note':'Values are API SI values. IDs are internal identifiers, not inferred physical labels. Inactive alternative parameters can also be present.'}

def snapshot(sw,model,project_name,directory,stage):
    """Vendor parametric-study XML includes named active settings omitted by EnumFeatures."""
    import json,hashlib,xml.etree.ElementTree as ET
    from sw_connect import get_com_member as get
    check=preflight(sw,model,project_name)
    dest=Path(directory)
    if not dest.is_absolute() or dest.exists():raise ValueError('NEW absolute snapshot directory required')
    dest.mkdir(parents=True)
    project=get(get(sw.GetAddInObject('FloWorks.App'),'GetAPI').GetDocument(model),'IActiveProject')
    path=dest/'settings.xml'
    stage('exporting_named_flow_settings',check)
    # Official SDK NIKCommonApi2.dll defines NIKParamFilter_all = -1.
    project.ExportParametersToFile(str(path),-1)
    if not path.is_file() or not path.stat().st_size:raise RuntimeError('Settings export did not create XML')
    root=ET.parse(path).getroot()
    if root.tag!='settings':raise ValueError('Unexpected vendor settings XML')
    def val(node,key):
        child=node.find(key)
        return child.get('value') if child is not None else None
    groups=[]
    for group in root.findall('FeaturesType'):
        features=[]
        for f in group.findall('Features'):
            features.append({'name':val(f,'FeatureNAME'),'uuid':val(f,'FeatureUUID'),
                'parameters':[{c.tag:c.get('value') for c in p if c.get('value') is not None} for p in f.findall('PS_Parameters')]})
        groups.append({'name':val(group,'FeatureGroupName'),'type':val(group,'FeatureType'),'features':features})
    result={'preflight':check,'groups':groups,'xml':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'note':'Named settings exported by vendor API. Raw XML preserves opaque fields and material data. Does not prove complete fan curves/topology or physical validity.'}
    (dest/'settings.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def set_parameter(sw,model,project_name,feature_uuid,parameter_id,expected_value,value_si,expected_unit,archive_directory,stage):
    import math,json,shutil,pythoncom,win32com.client
    from sw_connect import get_com_member as get
    before=parameters(sw,model,project_name)
    candidates=[f for f in before['features'] if f['uuid']==feature_uuid]
    if len(candidates)!=1:raise ValueError('Exact feature UUID required')
    item=next((q for q in candidates[0]['parameters'] if q['id']==parameter_id),None)
    if not item or 'error' in item:raise ValueError('Readable parameter required')
    if item['UnitID']!=expected_unit or item['value']!=expected_value:raise ValueError('Parameter value/unit changed; inspect again')
    if item['DependenceType']!=0 or item['Formula']:raise ValueError('Formula/table parameters require a dedicated adapter')
    if not math.isfinite(value_si):raise ValueError('Finite SI value required')
    if feature_uuid=='@global_mesh':
        if parameter_id==1181 and (value_si!=int(value_si) or not 1<=value_si<=7):raise ValueError('Mesh level must be integer 1..7')
        if parameter_id==1182 and value_si<=0:raise ValueError('Minimum gap must be positive meters')
    archive=Path(archive_directory);root=Path(before['preflight']['document']).parent.resolve()
    if not archive.is_absolute() or archive.exists() or archive.resolve().is_relative_to(root):raise ValueError('NEW archive outside model directory required')
    shutil.copytree(root,archive/'workspace-before-edit')
    (archive/'parameters-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    project=get(get(sw.GetAddInObject('FloWorks.App'),'GetAPI').GetDocument(model),'IActiveProject')
    feature=get(project,'GlobalMeshSettings') if feature_uuid=='@global_mesh' else next(f for f in get(project,'EnumFeatures') if get(f,'UUID_')==feature_uuid)
    stage('setting_flow_parameter',{'feature':feature_uuid,'parameter':parameter_id,'old_si':expected_value,'new_si':value_si})
    result_state(model,project,{'status':'stale','reason':'parameter_edit_started','archive':str(archive)})
    parameter=feature.GetParameter(parameter_id,'');parameter.value=value_si
    # Dynamic pywin32 returns this [out] VARIANT_BOOL as the Python result.
    returned=feature.ApplyUIChanges(project,False,False)
    actual=get(feature.GetParameter(parameter_id,''),'value')
    report={'feature_uuid':feature_uuid,'parameter_id':parameter_id,'before_si':expected_value,'after_si':actual,
            'apply_return':returned,'readback_matches':math.isclose(actual,value_si,rel_tol=1e-12,abs_tol=1e-12),
            'archive':str(archive),'results_stale':True,'note':'Re-solve required. Parameter meaning and active mode must be verified before editing.'}
    (archive/'parameter-edit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not returned or not report['readback_matches']:raise RuntimeError('Parameter apply/readback failed; inspect archive; no automatic retry')
    return report

def set_material(sw,model,project_name,feature_uuid,expected_path,material_path,archive_directory,stage):
    import shutil,json
    from sw_connect import get_com_member as get
    check=preflight(sw,model,project_name)
    project=get(get(sw.GetAddInObject('FloWorks.App'),'GetAPI').GetDocument(model),'IActiveProject')
    found=[f for f in get(project,'EnumFeatures') if get(f,'UUID_')==feature_uuid and get(f,'Type_')==21]
    if len(found)!=1:raise ValueError('Exact existing material-condition UUID required')
    feature=found[0];before=get(feature,'GetPathToSolidMaterial')
    if before!=expected_path:raise ValueError('Material assignment changed; inspect again')
    if not material_path or not isinstance(material_path,str):raise ValueError('Engineering-database material path required')
    archive=Path(archive_directory);root=Path(check['document']).parent.resolve()
    if not archive.is_absolute() or archive.exists() or archive.resolve().is_relative_to(root):raise ValueError('NEW archive outside model directory required')
    shutil.copytree(root,archive/'workspace-before-edit')
    before_record={'feature_uuid':feature_uuid,'before':before,'requested':material_path}
    (archive/'material-before.json').write_text(json.dumps(before_record,ensure_ascii=False,indent=2),encoding='utf-8')
    stage('setting_flow_material',before_record)
    result_state(model,project,{'status':'stale','reason':'material_edit_started','archive':str(archive)})
    accepted=feature.SetPathToSolidMaterial(material_path,project)
    if not accepted:raise RuntimeError('Material path rejected; inspect current state; no automatic retry')
    applied=feature.ApplyUIChanges(project,False,False)
    actual=get(feature,'GetPathToSolidMaterial')
    report={**before_record,'after':actual,'apply_return':applied,'readback_matches':actual==material_path,'results_stale':True,'archive':str(archive)}
    (archive/'material-edit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not applied or not report['readback_matches']:raise RuntimeError('Material apply/readback failed; inspect archive')
    return report

def solve_existing(sw, model, project_name, result_directory, archive_directory, stage):
    """Run an existing configured project; preserve its previous result directory first."""
    import json, shutil, time, psutil
    from sw_connect import get_com_member as get
    check = preflight(sw, model, project_name)
    if check['missing_active_references']: raise RuntimeError('Unresolved active model references')
    root = Path(check['document']).parent.resolve()
    source = Path(result_directory).resolve()
    archive = Path(archive_directory)
    if not Path(result_directory).is_absolute() or source.parent != root or not source.is_dir():
        raise ValueError('Result directory must be an existing direct child of the model directory')
    if not archive.is_absolute() or archive.exists() or archive.resolve().is_relative_to(root):
        raise ValueError('Archive must be a NEW absolute directory outside the model directory')
    stage('archiving_previous_flow_results', {'source': str(source), 'archive': str(archive)})
    # Preserve every sibling project too: a caller-selected result folder is
    # not authoritative evidence of where the Flow API will write.
    shutil.copytree(root, archive / 'workspace-before-solve')
    (archive / 'preflight.json').write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding='utf-8')
    settings=snapshot(sw,model,project_name,str(archive/'input-settings'),stage)
    project = get(get(sw.GetAddInObject('FloWorks.App'), 'GetAPI').GetDocument(model), 'IActiveProject')
    started = time.time()
    stage('starting_existing_flow_project', check)
    result_state(model,project,{'status':'stale','reason':'solve_started','archive':str(archive)})
    accepted = bool(project.Solve(True, True, True, False))
    while any((p.info['name'] or '').lower() == 'efdsolver.exe' for p in psutil.process_iter(['name'])):
        stage('waiting_for_flow_solver', {'elapsed_seconds': round(time.time()-started), 'archive': str(archive)})
        time.sleep(2)
    fresh = [p for p in source.rglob('*') if p.is_file() and p.stat().st_mtime >= started]
    logs = []
    for p in fresh:
        if p.name.lower() == 'efdsolver.log':
            raw = p.read_bytes()
            logs.append(raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8', errors='replace'))
    verified = any(p.suffix.lower() == '.fld' and p.stat().st_size > 0 for p in fresh) and any('Execution succeeded.' in t for t in logs)
    report = {'solve_return': accepted, 'solver_execution_verified': verified,
              'input_settings_xml':settings['xml'],'input_settings_sha256':settings['sha256'],
              'archive': str(archive), 'project': project_name, 'elapsed_seconds': time.time()-started,
              'fresh_files': [str(p) for p in fresh], 'retry_automatically': False}
    if verified:
        result_state(model,project,{'status':'verified_at_solve','input_settings_sha256':settings['sha256'],'archive':str(archive),
            'note':'Verified at solve completion. Manual/external changes are not tracked by this marker.'})
        report['results'] = results(sw, model, stage)
        used = [g for g in report['results']['goals'] if g['used_in_convergence']]
        report['all_convergence_goals_met'] = bool(used) and all(not g['invalid'] and g['progress'] >= 100 for g in used)
    else:
        report['note'] = 'Solve not verified. Inspect Flow dialogs/logs and selected result directory; no automatic retry.'
    (archive / 'solve-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report

def diagnose(sw, load, stage):
    dll = BASE / 'binCFW' / 'FW03.dll'
    result = {'installed_file': dll.is_file(), 'addin_path': str(dll),
              'load_requested': load, 'load_code': None, 'load_status': 'not_requested',
              'api_accessible': False, 'solver_verified': False,
              'base_license': 'not_verified_by_solve', 'electronics_license': 'not_tested',
              'hvac_license': 'not_tested', 'errors': []}
    stage('checking_flow_api')
    try:
        app = sw.GetAddInObject('FloWorks.App')
        result['api_accessible'] = app is not None
        if app is not None:
            info = app._oleobj_.GetTypeInfo()
            result['api_type'] = info.GetDocumentation(-1)[0]
    except Exception as exc:
        result['errors'].append(str(exc))
    if load and result['api_accessible']:
        result['load_status'] = 'reused_accessible_api'
    elif load and dll.is_file():
        from sw_connect import get_com_member as get
        # This installation faulted loading FW03 into an open-document session.
        # A clean restart followed by loading before opening recovered it.
        # Do not close or discard documents as part of diagnostics.
        documents = list(get(sw, 'GetDocuments') or [])
        result['open_document_count'] = len(documents)
        if documents:
            result['load_status'] = 'deferred_open_documents'
            result['recovery'] = 'Preserve open work, then load Flow in an empty healthy SW session before opening a model. No documents were closed.'
        else:
            stage('loading_flow_addin', {'path': str(dll)})
            try:
                code = int(sw.LoadAddIn(str(dll)))
                result.update(load_code=code, load_status=LOAD_CODES.get(code, 'unrecognized'))
                result['api_accessible'] = sw.GetAddInObject('FloWorks.App') is not None
            except Exception as exc:
                result['load_status'] = 'load_failed'
                result['errors'].append(str(exc))
                result['recovery'] = 'Inspect the SW session and Windows error log. Do not repeat LoadAddIn in a faulted session.'
    result['solver_file_exists'] = (BASE / 'binCFW' / 'efdsolver.exe').is_file()
    result['note'] = 'File presence and API access do not prove solver or extension licensing.'
    return result

def example(sw, output_directory, stage):
    """Prepare an isolated copy of the vendor conjugate heat-transfer example."""
    import shutil
    import pythoncom
    import win32com.client
    from sw_connect import get_com_member as get
    dest = Path(output_directory)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('A NEW absolute output directory is required')
    src = BASE / 'Examples' / 'A2 - Conjugate HT' / 'Ready'
    if not src.is_dir():
        raise FileNotFoundError(src)
    shutil.copytree(src, dest)
    path = dest / 'assembly.sldasm'
    stage('opening_official_example', {'path': str(path)})
    err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = sw.OpenDoc6(str(path), 2, 1, '', err, warn)
    if model is None or err.value:
        raise RuntimeError(f'Example open failed: {err.value}, warnings={warn.value}')
    # Verify references before allowing any future solve or model write.
    refs = [get(c, 'GetPathName') for c in (model.GetComponents(False) or [])]
    outside = [r for r in refs if r and not Path(r).resolve().is_relative_to(dest.resolve())]
    result = {'document': str(path), 'warnings': warn.value, 'outside_references': outside,
              'solver_verified': False, 'project_name': None}
    app = sw.GetAddInObject('FloWorks.App')
    if app is None:
        raise RuntimeError('Load Flow Simulation with sw_flow_diagnostics(load=true) first')
    api = get(app, 'GetAPI')
    doc = api.GetDocument(model)
    project = get(doc, 'IActiveProject') if doc is not None else None
    if project is not None:
        result['project_name'] = get(project, 'ProjectName')
    result['project_present'] = project is not None
    return result

def inspect_project(sw, model):
    from sw_connect import get_com_member as get
    app = sw.GetAddInObject('FloWorks.App')
    if app is None:
        raise RuntimeError('Flow add-in is not loaded')
    api = get(app, 'GetAPI')
    doc = api.GetDocument(model)
    project = get(doc, 'IActiveProject') if doc is not None else None
    return {'api_type': 'IAppApi', 'project_present': project is not None,
            'project_name': get(project, 'ProjectName') if project else None,
            'solver_verified': False}

def results(sw, model, stage):
    import pythoncom
    import win32com.client
    from sw_connect import get_com_member as get
    app = sw.GetAddInObject('FloWorks.App')
    if app is None:raise RuntimeError('Flow add-in is not loaded')
    doc = get(app,'GetAPI').GetDocument(model)
    project = get(doc,'IActiveProject')
    if project is None:raise RuntimeError('No active Flow project in specified document')
    post = get(project,'GetPostDocAPI')
    stage('loading_flow_results',{'project':get(project,'ProjectName')})
    get(post,'LoadLastResults')
    goals = get(post,'GetGoals')
    rows=[]
    for i in range(1,int(get(goals,'GetGoalsCount'))+1):
        g=goals.GetGoalByIndex(i)
        if g is None:raise RuntimeError(f'Flow goal index {i} is unavailable')
        rows.append({'name':get(g,'GetGoalName'),'value':get(g,'GetValue'),
                     'unit_enum':get(g,'GetUnit'),'progress':get(g,'GetProgress'),
                     'invalid':bool(get(g,'IsInvalid')),
                     'used_in_convergence':bool(get(g,'GetUseInConvergence'))})
        text=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BSTR,'')
        ok=project.SiToString(rows[-1]['unit_enum'],rows[-1]['value'],text)
        rows[-1]['display_value']=(next((v for v in ok if isinstance(v,str)),None) if isinstance(ok,tuple) else text.value) or None
        rows[-1]['display_unit']=project.GetUnitShortName(rows[-1]['unit_enum'])
    return {'project':get(project,'ProjectName'),'goals':rows,
            'freshness':result_state(model,project),
            'iterations':get(goals,'GetIterationsCount'),
            'note':'Values and units are reported directly by the Flow API; no guessed conversions.'}

def export_results(sw,model,directory,stage):
    import csv,json,html
    dest=Path(directory)
    if not dest.is_absolute() or dest.exists():raise ValueError('A NEW absolute output directory is required')
    data=results(sw,model,stage)
    dest.mkdir(parents=True)
    (dest/'goals.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    with (dest/'goals.csv').open('w',encoding='utf-8-sig',newline='') as f:
        if data['goals']:
            writer=csv.DictWriter(f,fieldnames=list(data['goals'][0]));writer.writeheader();writer.writerows(data['goals'])
    image=dest/'current-view.bmp'
    stage('exporting_flow_view')
    if not model.SaveBMP(str(image),0,0) or not image.is_file():raise RuntimeError('View export failed; table files remain in output directory')
    used=[g for g in data['goals'] if g['used_in_convergence']]
    converged=bool(used) and all(not g['invalid'] and g['progress']>=100 for g in used)
    rows=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
        (g['name'],g['display_value'],g['display_unit'],g['progress'],g['used_in_convergence'],g['invalid']))+'</tr>' for g in data['goals'])
    (dest/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Flow results</title>'
        '<style>body{font:16px sans-serif;margin:40px;max-width:1200px}td,th{padding:8px;border:1px solid #ddd}table{border-collapse:collapse}img{max-width:100%}</style>'
        '<h1>'+html.escape(str(data['project']))+'</h1><p>Iterations: '+str(data['iterations'])+
        ' · All selected convergence goals met: '+str(converged)+'</p>'
        '<p>Result freshness: '+html.escape(str(data['freshness']['status']))+'. Last loaded results. Convergence does not establish physical accuracy or freshness. The image is the current viewport; plot creation is separate.</p>'
        '<table><tr><th>Goal</th><th>Value</th><th>Unit</th><th>Progress</th><th>Convergence goal</th><th>Invalid</th></tr>'+rows+'</table>'
        '<h2>Current viewport</h2><img src="current-view.bmp">',encoding='utf-8')
    return {'files':[{'path':str(p),'bytes':p.stat().st_size} for p in dest.iterdir()],
            'note':'Captures the current viewport. Configure and visually verify a Flow plot first; this tool does not create a plot.'}

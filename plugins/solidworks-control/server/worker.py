from pathlib import Path
import json,sys,time,traceback,math
import pythoncom,win32com.client,comtypes.client,psutil
from jobs import ROOT,JOBS,LOCK,atomic,health,release_recorded_job
from portable_paths import constants, templates as template_dir
sys.path.insert(0,str(Path(__file__).resolve().parent/'helpers'))
from sw_connect import get_com_member as get,new_document
def ref():return win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
def null():return win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
def docs(sw):return list(get(sw,'GetDocuments') or [])
def summary(m):
    return {'title':get(m,'GetTitle'),'path':get(m,'GetPathName'),'type':int(get(m,'GetType')),'dirty':bool(get(m,'GetSaveFlag'))}
def document(sw,identity):
    if not identity:raise ValueError('Exact document path or title required; active document is not an implicit target')
    found=[m for m in docs(sw) if identity.casefold() in (str(get(m,'GetPathName')).casefold(),str(get(m,'GetTitle')).casefold())]
    if len(found)!=1:raise ValueError(f'Document identity matched {len(found)} documents')
    return found[0]
def output(name,exts):
    p=Path(name)
    if not p.is_absolute():raise ValueError('Absolute output path required')
    if p.suffix.lower() not in exts:raise ValueError('Unsupported output format')
    if p.exists():raise FileExistsError('Refusing to overwrite existing output')
    p.parent.mkdir(parents=True,exist_ok=True);return p
def activate(sw,m):
    e=ref();ret=sw.ActivateDoc3(get(m,'GetTitle'),False,0,e)
    if ret is None or e.value:raise RuntimeError(f'Activation failed: {e.value}')
def templates(sw,repair=False):
    c=comtypes.client.GetModule(str(constants()))
    base=template_dir();rows=[]
    for key,fn in [(c.swDefaultTemplatePart,'gb_part.prtdot'),(c.swDefaultTemplateAssembly,'gb_assembly.asmdot')]:
        old=sw.GetUserPreferenceStringValue(key);row={'key':key,'value':old,'exists':bool(old and Path(old).is_file())}
        if repair and not row['exists']:
            candidate=base/fn
            if not candidate.is_file():raise FileNotFoundError(candidate)
            stage('repair_template',row)
            if not sw.SetUserPreferenceStringValue(key,str(candidate)):raise RuntimeError('Template setting rejected')
            row['repaired_to']=str(candidate)
        rows.append(row)
    return rows
def execute(action,a):
    procs=[p for p in health()['processes'] if p['name'].lower()=='sldworks.exe']
    if action=='start' and not procs:
        stage('launching');sw=win32com.client.Dispatch('SldWorks.Application')
    else:
        from live_session import connect_existing
        try:sw=connect_existing()
        except pythoncom.com_error:raise RuntimeError('No accessible SW COM session. Start explicitly if no process; otherwise inspect session/elevation, never spawn a duplicate.')
    sw.Visible=True
    if action=='start':sw.UserControl=True
    if action in ('start','session'):
        return {'revision':get(sw,'RevisionNumber'),'active':summary(sw.ActiveDoc) if sw.ActiveDoc else None,'documents':[summary(m) for m in docs(sw)][:300],'templates':templates(sw)}
    if action=='repair_templates':return {'templates':templates(sw,True)}
    if action=='flow_sdk_probe':
        from probe_flow_sdk import run
        return run(stage)
    if action=='flow_diagnostics':
        from flow_tools import diagnose
        return diagnose(sw, bool(a.get('load',False)), stage)
    if action=='flow_example':
        from flow_tools import example
        return example(sw, a['output_directory'], stage)
    if action=='open':
        p=Path(a['path']);ext=p.suffix.lower()
        if not p.is_file():raise FileNotFoundError(p)
        existing=[m for m in docs(sw) if str(get(m,'GetPathName')).casefold()==str(p).casefold()]
        if existing:return {'reused':True,'document':summary(existing[0])}
        e,w=ref(),ref();stage('opening',{'path':str(p),'bytes':p.stat().st_size})
        if ext in ('.sldprt','.sldasm','.slddrw'):
            m=sw.OpenDoc6(str(p),{'.sldprt':1,'.sldasm':2,'.slddrw':3}[ext],1|(2 if a.get('read_only',True) else 0),'',e,w)
        elif ext in ('.step','.stp','.igs','.iges','.x_t','.x_b'):
            if not all(x['exists'] for x in templates(sw)):raise RuntimeError('Invalid default templates; repair_templates before import')
            c=comtypes.client.GetModule(str(constants()))
            keys=[c.swMultiCAD_Enable3DInterconnect,c.swImportMultBodyAsPartData]
            before={k:sw.GetUserPreferenceToggle(k) for k in keys};atomic(FOLDER/'import_settings_backup.json',before)
            try:
                sw.SetUserPreferenceToggle(keys[0],False)
                sw.SetUserPreferenceToggle(keys[1],False)
                m=sw.LoadFile4(str(p),'r',null(),e)
            finally:
                for k,v in before.items():sw.SetUserPreferenceToggle(k,v)
        else:raise ValueError('Unsupported input format')
        return {'status':'opened' if m is not None and not e.value else 'partial_or_failed','errors':e.value,'warnings':w.value,'document':summary(m) if m is not None else None,'note':'Imported neutral file is a new document; read_only applies to native files.'}
    if action=='create_cylinder':
        radius=float(a['radius_mm']);height=float(a['height_mm'])
        if not 0<radius<=1000 or not 0<height<=10000:raise ValueError('Dimensions out of range')
        p=output(a['output_path'],{'.sldprt'})
        m=new_document(sw,'part',str(template_dir()/'gb_part.prtdot'))
        if m is None:raise RuntimeError('New part failed')
        from sw_part import sketch,sketch_circle,extrude_boss
        f=get(m,'FirstFeature');plane=None
        while f:
            if get(f,'GetTypeName2')=='RefPlane':plane=f.Name;break
            f=get(f,'GetNextFeature')
        if not plane:raise RuntimeError('No reference plane')
        with sketch(m,plane) as name:
            if sketch_circle(m,0,0,radius/1000) is None:raise RuntimeError('Circle failed')
        if extrude_boss(m,name,height/1000) is None:raise RuntimeError('Extrusion failed')
        bodies=m.GetBodies2(0,False) or [];volume=sum(b.GetMassProperties(1)[3] for b in bodies)
        expected=math.pi*(radius/1000)**2*height/1000
        if len(bodies)!=1 or abs(volume-expected)>expected*1e-5:raise RuntimeError('Geometry verification failed')
        e,w=ref(),ref();ok=m.Extension.SaveAs(str(p),0,1,null(),e,w)
        if not ok or e.value or not p.exists():raise RuntimeError(f'Save failed {e.value}')
        return {'document':summary(m),'bodies':len(bodies),'volume_m3':volume,'expected_volume_m3':expected,'bytes':p.stat().st_size}
    if action=='validate_interference':
        from validate_interference import run
        return run(sw,a['output_directory'],lambda args:execute('create_cylinder',args),stage,
                   document(sw,a['resume_document']) if a.get('resume_document') else None)
    if action=='create_part':
        from model_tools import create_part
        return create_part(sw,a['plan'],a['output_path'],stage)
    if action=='create_assembly':
        from model_tools import create_assembly
        return create_assembly(sw,a['plan'],a['output_path'],stage)
    if action=='create_drawing':
        from model_tools import create_drawing
        return create_drawing(sw,a['plan'],a['output_path'],stage)
    m=document(sw,a['document']);stage(action,summary(m))
    if action=='compare_assembly_geometry':
        from assembly_tools import compare_assembly_geometry
        return compare_assembly_geometry(document(sw,a['source_document']),m)
    if action=='externalize_virtual_copy':
        from virtual_tools import externalize_copy
        return externalize_copy(sw,m,a['output_directory'],stage)
    if action=='validate_virtual_externalize':
        from validate_virtual_externalize import run
        activate(sw,m)
        return run(sw,m,stage)
    if action=='validate_virtual_reopen':
        from validate_virtual_externalize import verify
        return verify(sw,m)
    if action=='validate_virtual_package':
        from validate_virtual_externalize import verify_package
        return verify_package(sw,m)
    if action=='flow_feature_editor':
        from flow_tools import preflight
        check=preflight(sw,m,a['project_name'])
        callbacks={'volume_source':'TB_RUN_dialog_Volume_Sources','global_goal':'TB_RUN_dialog_Global_Goal','volume_goal':'TB_RUN_dialog_Volume_Goal'}
        callback=callbacks[a['kind']]
        activate(sw,m);m.ClearSelection2(True)
        get(sw.GetAddInObject('FloWorks.App'),callback)
        return {'editor_invoked':a['kind'],'preflight':check,'feature_created':False,
                'note':'Finish and verify observed editor UI; invocation is not feature creation.'}
    if action=='flow_new_project_wizard':
        if int(get(m,'GetType')) not in (1,2) or not Path(get(m,'GetPathName')).is_file():
            raise ValueError('Saved native part or assembly required for Flow project creation')
        activate(sw,m)
        app=sw.GetAddInObject('FloWorks.App')
        if app is None:raise RuntimeError('Flow API unavailable')
        stage('opening_flow_project_wizard',summary(m))
        get(app,'TB_MakeNewProject_WIZARD')
        return {'wizard_invoked':True,'document':summary(m),'project_created':False,
                'note':'Complete and inspect wizard UI; invocation does not prove project creation.'}
    if action=='flow_preflight':
        from flow_tools import preflight
        return preflight(sw,m,a['project_name'])
    if action=='flow_parameters':
        from flow_tools import parameters
        return parameters(sw,m,a['project_name'])
    if action=='flow_snapshot':
        from flow_tools import snapshot
        return snapshot(sw,m,a['project_name'],a['output_directory'],stage)
    if action=='flow_set_material':
        from flow_tools import set_material
        activate(sw,m)
        return set_material(sw,m,a['project_name'],a['feature_uuid'],a['expected_path'],a['material_path'],a['archive_directory'],stage)
    if action=='flow_set_parameter':
        from flow_tools import set_parameter
        activate(sw,m)
        return set_parameter(sw,m,a['project_name'],a['feature_uuid'],a['parameter_id'],a['expected_value'],a['value_si'],a['expected_unit'],a['archive_directory'],stage)
    if action=='flow_solve':
        from flow_tools import solve_existing
        activate(sw,m)
        return solve_existing(sw,m,a['project_name'],a['result_directory'],a['archive_directory'],stage)
    if action=='flow_project':
        from flow_tools import inspect_project
        return inspect_project(sw,m)
    if action=='flow_results':
        from flow_tools import results
        activate(sw,m)
        return results(sw,m,stage)
    if action=='flow_export':
        from flow_tools import export_results
        activate(sw,m)
        return export_results(sw,m,a['output_directory'],stage)
    if action=='inspect':
        out=summary(m);features=[];f=get(m,'FirstFeature')
        while f and len(features)<300:
            features.append({'name':f.Name,'type':get(f,'GetTypeName2')});f=get(f,'GetNextFeature')
        out['features']=features;out['features_truncated']=f is not None
        if out['type']==1:
            bodies=m.GetBodies2(0,False) or [];out['solid_bodies']=len(bodies);out['body_bounds_m']=[list(b.GetBodyBox()) for b in bodies[:100]]
        return out
    if action=='components':
        if get(m,'GetType')!=2:raise ValueError('Assembly required')
        cs=m.GetComponents(True) or [];items=[]
        for c in cs[:500]:
            tr=c.Transform2
            items.append({'name':c.Name2,'path':get(c,'GetPathName'),'suppression':get(c,'GetSuppression'),'transform':list(tr.ArrayData) if tr else None})
        return {'total':len(cs),'components':items,'truncated':len(cs)>500,'scope':'top-level'}
    if action=='interference':
        from assembly_tools import interference
        activate(sw,m)
        return interference(m,stage)
    if action=='pack_inventory':
        from assembly_tools import pack_inventory
        activate(sw,m)
        return pack_inventory(m,stage,bool(a.get('signature_only',False)))
    if action=='replace_component_copy':
        from assembly_tools import replace_copy
        activate(sw,m)
        return replace_copy(sw,m,a['component_name'],a['expected_path'],a['replacement_path'],a['output_path'],stage)
    if action=='validate_mate_fixture':
        from validate_interference import mate_fixture
        return mate_fixture(sw,m,a['output_path'],stage)
    if action=='mate_status':
        from assembly_tools import mate_status
        return mate_status(m)
    if action=='geometry_inventory':
        from assembly_tools import geometry_inventory
        return geometry_inventory(m)
    if action=='virtual_components':
        from assembly_tools import virtual_components
        return virtual_components(m)
    if action=='dependency_inventory':
        from assembly_tools import dependency_inventory
        return dependency_inventory(sw,m)
    if action=='copy_dependency_package':
        from assembly_tools import copy_dependency_package
        return copy_dependency_package(sw,m,a['output_directory'],stage,a.get('reference_remap'))
    if action=='view':
        views={'isometric':7,'front':1,'back':2,'left':3,'right':4,'top':5,'bottom':6}
        activate(sw,m);m.ShowNamedView2('',views[a['view']]);get(m,'ViewZoomtofit2')
        p=output(a['output_path'],{'.bmp'})
        if not m.SaveBMP(str(p),0,0) or not p.exists():raise RuntimeError('Preview failed')
        return {'document':summary(m),'preview':str(p),'bytes':p.stat().st_size}
    if action=='activate':activate(sw,m);return summary(m)
    if action=='save_copy':
        p=output(a['output_path'],{'.sldprt','.sldasm','.slddrw','.step','.stp','.x_t','.stl'})
        native={1:'.sldprt',2:'.sldasm',3:'.slddrw'}[get(m,'GetType')]
        if p.suffix.lower().startswith('.sld') and p.suffix.lower()!=native:raise ValueError('Native extension must match document type')
        old=get(m,'GetPathName');activate(sw,m);m.ClearSelection2(True);e,w=ref(),ref()
        ok=m.Extension.SaveAs(str(p),0,3,null(),e,w)
        if not ok or e.value or not p.exists():raise RuntimeError(f'Copy/export failed: errors={e.value}, warnings={w.value}')
        return {'output':str(p),'bytes':p.stat().st_size,'errors':e.value,'warnings':w.value,'source_path_unchanged':get(m,'GetPathName')==old,'note':'Assembly copy is not Pack and Go; dependencies retain their paths.'}
    if action=='close_clean':
        if get(m,'GetSaveFlag'):raise RuntimeError('Document has unsaved changes; refusing discard')
        title=get(m,'GetTitle');sw.CloseDoc(title)
        if any(get(d,'GetTitle')==title for d in docs(sw)):
            raise RuntimeError('Close request returned but document is still open')
        return {'closed':title,'verified':True}
    raise ValueError('Unknown action')
if __name__=='__main__':
    jid=sys.argv[1];FOLDER=JOBS/jid
    def stage(name,data=None):atomic(FOLDER/'stage.json',{'stage':name,'time':time.time(),'data':data})
    pythoncom.CoInitialize()
    try:
        req=json.loads((FOLDER/'request.json').read_text('utf-8'));stage('connecting')
        result=execute(req['action'],req['args']);atomic(FOLDER/'result.json',{'status':'completed','job_id':jid,'result':result})
    except Exception as exc:
        atomic(FOLDER/'result.json',{'status':'failed','job_id':jid,'error':str(exc),'traceback':traceback.format_exc(),'retry_automatically':False})
    finally:
        release_recorded_job(jid)
        pythoncom.CoUninitialize()

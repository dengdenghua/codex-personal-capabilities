"""Externalize copy-owned embedded components without saving original assemblies."""
from pathlib import Path
import hashlib
import math
import pythoncom
import win32com.client
from sw_connect import get_com_member as get
from assembly_tools import mate_status, virtual_components
from jobs import atomic

def _ref():return win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
def _hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _same(a,b):return len(a)==len(b) and all(math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-12) for x,y in zip(a,b))

def externalize_copy(sw,model,output_directory,stage):
    root=Path(output_directory)
    if not root.is_absolute() or root.exists():raise ValueError('NEW absolute output directory required')
    if int(get(model,'GetType'))!=2:raise ValueError('Assembly required')
    source=Path(get(model,'GetPathName'))
    if not source.is_file():raise ValueError('Saved source assembly required')
    if get(model,'GetSaveFlag'):raise ValueError('Source has unsaved changes; preserve and save an authorized working copy first')
    original_virtual=virtual_components(model)
    original_paths={row['path'].casefold() for row in original_virtual['virtual_components']}
    deps=list(sw.GetDocumentDependencies2(str(source),True,True,False) or [])
    if len(deps)%2:raise RuntimeError('Unexpected dependency layout')
    paths={source,*[Path(deps[i]) for i in range(1,len(deps),2) if Path(deps[i]).is_file()]}
    hashes={str(p):_hash(p) for p in paths}
    suffix=hashlib.sha256(str(root).casefold().encode()).hexdigest()[:12]
    destination=root/('assembly_'+suffix+'.SLDASM')
    root.mkdir(parents=True)
    report={'source':str(source),'output':str(destination),'created':False,'externalized':[],'blocked':[],
            'source_hashes':hashes,'complete_virtual_externalization':False,'package_verified':False,
            'note':'Isolated preparation copy; existing external component references remain. Dependency packaging and reopen checks are separate.'}
    def publish():atomic(root/'externalize-report.json',report)
    publish()
    e,w=_ref(),_ref()
    stage('copying_assembly_for_virtual_externalization',{'source':str(source),'output':str(destination)})
    sw.ActivateDoc3(get(model,'GetTitle'),False,0,e)
    if e.value:raise RuntimeError(f'Activation error {e.value}')
    model.ClearSelection2(True)
    null=win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
    try:
        if not model.Extension.SaveAs(str(destination),0,3,null,e,w) or e.value or not destination.is_file():raise RuntimeError(f'Copy failed {e.value}, warnings={w.value}')
        report['created']=True
        copy=sw.OpenDoc6(str(destination),2,1,'',e,w)
        report['open_errors']=e.value;report['open_warnings']=w.value
        if copy is None or e.value:raise RuntimeError(f'Copy open failed {e.value}; inspect created files before retry')
        report['mates_before']=mate_status(copy)
        processed=set()
        def visit(owner):
            owner_path=Path(get(owner,'GetPathName'))
            if not owner_path.is_relative_to(root):raise RuntimeError('Refusing to modify an assembly outside the new copy directory')
            if owner_path in processed:return
            processed.add(owner_path)
            if len(processed)>100:raise RuntimeError('Embedded assembly limit exceeded; inspect partial output')
            for component in list(owner.GetComponents(True) or []):
                if not get(component,'IsVirtual'):continue
                old_path=get(component,'GetPathName')
                child=get(component,'GetModelDoc2')
                if old_path.casefold() in original_paths:
                    raise RuntimeError('Copy still shares original virtual identity; refusing externalization')
                if child is None:
                    report['blocked'].append({'name':component.Name2,'reason':'Virtual model unavailable; no automatic resolve'})
                    continue
                kind=int(get(child,'GetType'))
                if kind not in (1,2):raise ValueError('Unsupported virtual document type')
                transform=list(component.Transform2.ArrayData)
                token=hashlib.sha256((str(root)+'|'+old_path).casefold().encode()).hexdigest()[:16]
                target=root/('embedded_'+token+('.SLDPRT' if kind==1 else '.SLDASM'))
                if target.exists():raise FileExistsError(target)
                stage('externalizing_copy_owned_component',{'name':component.Name2,'output':str(target)})
                ok=bool(component.SaveVirtualComponent(str(target)))
                item={'old_virtual_path':old_path,'output':str(target),'accepted':ok,
                      'reference_verified':not bool(get(component,'IsVirtual')) and Path(get(component,'GetPathName'))==target,
                      'transform_preserved':_same(transform,list(component.Transform2.ArrayData))}
                report['externalized'].append(item);publish()
                if not ok or not item['reference_verified'] or not item['transform_preserved'] or not target.is_file():raise RuntimeError('Externalization verification failed; no automatic retry')
                if kind==2:visit(get(component,'GetModelDoc2'))
            rebuilt=bool(get(owner,'EditRebuild3'))
            error,warning=_ref(),_ref()
            saved=bool(owner.Save3(1,error,warning))
            report.setdefault('saved_assemblies',[]).append({'document':str(owner_path),'rebuilt':rebuilt,'saved':saved,'errors':error.value,'warnings':warning.value})
            if not rebuilt or not saved or error.value:raise RuntimeError('Copy rebuild/save failed')
        visit(copy)
        report['remaining_virtual_components']=virtual_components(copy)['virtual_components']
        report['mates_after']=mate_status(copy)
        report['source_virtual_identity_unchanged']=virtual_components(model)==original_virtual
        report['source_files_unchanged']=all(_hash(Path(p))==h for p,h in hashes.items())
        before=report['mates_before'];after=report['mates_after']
        report['mates_preserved']=before==after and after['errors_readable'] and not after['nonzero_errors']
        report['complete_virtual_externalization']=not report['blocked'] and not report['remaining_virtual_components'] and report['source_virtual_identity_unchanged'] and report['source_files_unchanged'] and report['mates_preserved']
        publish()
        return report
    except Exception as exc:
        report['error']=str(exc)
        report['retry_automatically']=False
        report['source_files_unchanged']=all(_hash(Path(p))==h for p,h in hashes.items())
        publish()
        raise

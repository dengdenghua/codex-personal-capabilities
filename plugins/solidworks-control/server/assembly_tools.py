"""Assembly checks through the shared CAD worker; never save source documents."""
from sw_connect import get_com_member as get


def virtual_components(model):
    if int(get(model,'GetType'))!=2:
        raise ValueError('Assembly required')
    rows=[]
    for component in model.GetComponents(False) or []:
        actual_virtual=bool(get(component,'IsVirtual'))
        component_path=get(component,'GetPathName')
        if not actual_virtual and '^' not in component_path and '^' not in component.Name2:
            continue
        doc=get(component,'GetModelDoc2')
        row={'name':component.Name2,'path':component_path,
             'suppression':int(get(component,'GetSuppression')),'is_virtual':actual_virtual,
             'model_available':doc is not None}
        if doc is not None:
            row['document_type']=int(get(doc,'GetType'))
            if row['document_type']==1:
                row['solid_bodies']=len(doc.GetBodies2(0,False) or [])
        rows.append(row)
    return {'document':get(model,'GetPathName'),'virtual_components':rows,
            'note':'Read-only inventory; suppressed virtual components may be unavailable without being missing. No resolve, externalize or save performed.'}


def dependency_inventory(sw, model):
    path=get(model,'GetPathName')
    if not path:
        raise ValueError('Saved native document required')
    values=list(sw.GetDocumentDependencies2(path,True,True,False) or [])
    if len(values)%2:
        raise RuntimeError('Unexpected dependency result layout')
    return {'document':path,'dependencies':[{'name':values[i],'path':values[i+1]} for i in range(0,len(values),2)],
            'source_dirty':bool(get(model,'GetSaveFlag')),'scope':'Saved document dependency inventory'}


def copy_dependency_package(sw, model, output_directory, stage, reference_remap=None):
    import hashlib
    import json
    import shutil
    from pathlib import Path
    remap={Path(old):Path(new) for old,new in (reference_remap or {}).items()}
    for old,new in remap.items():
        if not old.is_absolute() or old.exists() or not new.is_absolute() or not new.is_file() or old.name.casefold()!=new.name.casefold():
            raise ValueError('Remap requires a missing absolute old path and existing same-filename absolute replacement')
    inventory=dependency_inventory(sw,model)
    root=Path(output_directory)
    if not root.is_absolute() or root.exists():
        raise ValueError('New absolute package directory required')
    source=Path(inventory['document'])
    pending=[source]
    graph={}
    raw_graph={}
    used_remap={}
    missing=[]
    while pending:
        original=pending.pop()
        if original in graph:
            continue
        if len(graph)>=1000:
            raise ValueError('Dependency graph exceeds 1000 files; no package created')
        if not original.is_file():
            missing.append(str(original))
            graph[original]=[]
            continue
        direct=list(sw.GetDocumentDependencies2(str(original),False,True,False) or [])
        if len(direct)%2:
            raise RuntimeError('Unexpected direct dependency layout')
        raw_graph[original]=list(dict.fromkeys(Path(direct[i]) for i in range(1,len(direct),2)))
        graph[original]=list(dict.fromkeys(remap.get(p,p) for p in raw_graph[original]))
        used_remap.update({str(p):str(remap[p]) for p in raw_graph[original] if p in remap})
        pending.extend(p for p in graph[original] if p not in graph)
        stage('enumerating_dependency_graph',{'files':len(graph),'pending':len(pending),'current':str(original)})
    paths=[p for p in graph if p!=source]
    if missing:
        return {'package_verified':False,'created':False,'missing_or_virtual_dependencies':missing,
                'applied_reference_remap':used_remap,
                'files_in_graph':len(graph),'note':'Complete graph includes in-context references. Missing/virtual paths require resolution; no files copied.'}
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,*paths]}
    # Unique names also avoid SW resolving an already-open original by basename.
    def target(p):
        identity=str(root).casefold()+'|'+str(p).casefold()
        return root/(p.stem+'_'+hashlib.sha256(identity.encode()).hexdigest()[:10]+p.suffix)
    destination=target(source)
    targets=[target(p) for p in paths]
    root.mkdir(parents=True)
    plan={'source':str(source),'output':str(destination),
          'applied_reference_remap':used_remap,
          'mapping':dict(zip(map(str,paths),map(str,targets))),
          'source_dirty':inventory['source_dirty'],'note':'Copies saved disk state, not unsaved in-memory edits.'}
    (root/'package-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf-8')
    stage('copying_dependency_package',plan)
    mapping={source:destination,**dict(zip(paths,targets))}
    for original,copied in mapping.items():
        shutil.copy2(original,copied)
    rewrites=[]
    for original,copied in mapping.items():
        for old in raw_graph[original]:
            resolved=remap.get(old,old)
            if resolved not in mapping:
                raise RuntimeError(f'Dependency outside enumerated graph: {old}')
            accepted=bool(sw.ReplaceReferencedDocument(str(copied),str(old),str(mapping[resolved])))
            rewrites.append({'document':str(copied),'old':str(old),'new':str(mapping[resolved]),'accepted':accepted})
            if not accepted:
                raise RuntimeError(f'Reference rewrite rejected: {rewrites[-1]}')
    absent=[str(p) for p in [destination,*targets] if not p.is_file()]
    references=list(sw.GetDocumentDependencies2(str(destination),True,True,False) or [])
    if len(references)%2:
        raise RuntimeError('Unexpected copied dependency result')
    copied_refs=[str(references[i]) for i in range(1,len(references),2)]
    external=[p for p in copied_refs if not Path(p).is_relative_to(root)]
    mismatches=[]
    for original,copied in mapping.items():
        actual=list(sw.GetDocumentDependencies2(str(copied),False,True,False) or [])
        if len(actual)%2:
            raise RuntimeError('Unexpected copied direct dependency layout')
        observed={Path(actual[i]) for i in range(1,len(actual),2)}
        expected={mapping[p] for p in graph[original]}
        if observed!=expected:
            mismatches.append({'document':str(copied),'expected':list(map(str,expected)),'observed':list(map(str,observed))})
    unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in hashes.items())
    report={**plan,'method':'file_copy_and_ReplaceReferencedDocument','rewrites':rewrites,'missing_outputs':absent,'copied_references':copied_refs,
            'external_references':external,'source_files_unchanged':unchanged,
            'reference_mismatches':mismatches,'opened_verified':False,
            'verification_scope':'Saved native CAD dependency graph only. Open/rebuild validation and simulation sidecar files are separate.',
            'package_verified':not absent and not external and unchanged and not mismatches}
    (root/'package-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return report


def geometry_inventory(model):
    rows=[]
    for component in model.GetComponents(False) or []:
        doc=get(component,'GetModelDoc2')
        if doc is None:
            rows.append({'name':component.Name2,'unavailable':True})
        elif int(get(doc,'GetType'))==1:
            bodies=list(doc.GetBodies2(0,False) or [])
            scale=float(component.Transform2.ArrayData[12])
            rows.append({'name':component.Name2,'bodies':len(bodies),
                         'volume_m3':sum(b.GetMassProperties(1)[3] for b in bodies)*abs(scale)**3,
                         'transform':list(component.Transform2.ArrayData)})
    return {'components':rows,'note':'Volumes sum individual solids, including overlap; not union volume.'}


def compare_assembly_geometry(source, candidate):
    """Compare current resolved solid instances as a multiset; unavailable models fail."""
    import math
    before=geometry_inventory(source)['components']
    after=geometry_inventory(candidate)['components']
    unmatched=list(after)
    matches=[]
    for old in before:
        found=[new for new in unmatched if not old.get('unavailable') and not new.get('unavailable')
               and old['bodies']==new['bodies']
               and math.isclose(old['volume_m3'],new['volume_m3'],rel_tol=1e-9,abs_tol=1e-14)
               and len(old['transform'])==len(new['transform'])
               and all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-12) for a,b in zip(old['transform'],new['transform']))]
        if found:
            matches.append({'source':old['name'],'candidate':found[0]['name']})
            unmatched.remove(found[0])
    return {'instance_volumes_and_transforms_match':bool(before) and len(matches)==len(before)==len(after),
            'source_instances':before,'candidate_instances':after,'matches':matches,
            'source_mates':mate_status(source),'candidate_mates':mate_status(candidate),
            'scope':'Current configuration solid instance body counts, volumes and transforms, plus root mate errors. Equal volume is not proof of identical surface geometry; empty subassemblies and other configurations require separate checks.'}


def mate_status(model):
    if int(get(model, 'GetType')) != 2:
        raise ValueError('Assembly required')
    rows = []
    def read(feature, nested=False):
        while feature:
            kind = get(feature, 'GetTypeName2')
            if kind.startswith('Mate') and kind != 'MateGroup':
                row = {'name': feature.Name, 'type': kind}
                try:
                    row['error_code'] = int(get(feature, 'GetErrorCode'))
                except Exception as exc:
                    row['read_error'] = str(exc)
                rows.append(row)
            child = get(feature, 'GetFirstSubFeature')
            if child is not None:
                read(child, True)
            feature = get(feature, 'GetNextSubFeature' if nested else 'GetNextFeature')
    read(get(model, 'FirstFeature'))
    return {'mates': rows, 'errors_readable': all('error_code' in r for r in rows),
            'nonzero_errors': [r for r in rows if r.get('error_code',0) != 0]}


def replace_copy(sw, model, component_name, expected_path, replacement_path, output_path, stage):
    import json
    import math
    import hashlib
    from pathlib import Path
    import pythoncom
    import win32com.client
    def ref():
        return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    def empty():
        return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    def find(doc):
        matches = [c for c in doc.GetComponents(True) or [] if c.Name2 == component_name]
        if len(matches) != 1:
            raise ValueError('Expected exactly one named top-level component')
        component = matches[0]
        if Path(get(component, 'GetPathName')) != Path(expected_path):
            raise ValueError('Component reference changed; refusing replacement')
        return component
    if int(get(model, 'GetType')) != 2 or not get(model, 'GetPathName'):
        raise ValueError('Assembly with an existing saved path required')
    source_dirty = bool(get(model, 'GetSaveFlag'))
    source = Path(get(model, 'GetPathName'))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    replacement = Path(replacement_path)
    dest = Path(output_path)
    if not Path(expected_path).is_absolute():
        raise ValueError('Absolute expected component path required')
    if not replacement.is_absolute() or not replacement.is_file() or replacement.suffix.lower() not in ('.sldprt', '.sldasm'):
        raise ValueError('Existing absolute native replacement path required')
    if not dest.is_absolute() or dest.suffix.lower() != '.sldasm' or dest.exists() or Path(str(dest)+'.replacement.json').exists() or dest.stem.casefold() == source.stem.casefold():
        raise ValueError('New absolute assembly path with a distinct filename required')
    old = find(model)
    if get(old, 'GetModelDoc2') is None:
        raise ValueError('Resolve the selected component first')
    before_transform = list(old.Transform2.ArrayData)
    before_mates = len(get(old, 'GetMates') or [])
    dest.parent.mkdir(parents=True, exist_ok=True)
    error, warning = ref(), ref()
    model.ClearSelection2(True)
    stage('saving_replacement_working_copy', {'output': str(dest)})
    if not model.Extension.SaveAs(str(dest), 0, 3, empty(), error, warning) or error.value or not dest.is_file():
        raise RuntimeError('Could not create assembly working copy')
    copied = sw.OpenDoc6(str(dest), 2, 1, '', error, warning)
    if copied is None or error.value:
        raise RuntimeError('Working copy could not be opened')
    activated = sw.ActivateDoc3(get(copied, 'GetTitle'), False, 0, error)
    if activated is None or error.value:
        raise RuntimeError('Working copy activation failed')
    target = find(copied)
    names_before = {c.Name2 for c in copied.GetComponents(True) or [] if c.Name2 != component_name}
    copied.ClearSelection2(True)
    if not target.Select4(False, empty(), False):
        raise RuntimeError('Exact component selection failed')
    stage('replacing_component', {'component': component_name, 'replacement': str(replacement)})
    accepted = bool(copied.ReplaceComponents2(str(replacement), '', False, 0, True))
    copied.ClearSelection2(True)
    rebuild = bool(get(copied, 'EditRebuild3'))
    candidates = [c for c in copied.GetComponents(True) or [] if c.Name2 not in names_before and Path(get(c, 'GetPathName')) == replacement]
    if not accepted or len(candidates) != 1:
        raise RuntimeError('Replacement was not verified; inspect working copy before retrying')
    updated = candidates[0]
    after_transform = list(updated.Transform2.ArrayData)
    after_mates = len(get(updated, 'GetMates') or [])
    preserved = len(after_transform) == len(before_transform) and all(math.isclose(a,b,abs_tol=1e-9,rel_tol=1e-9) for a,b in zip(before_transform,after_transform))
    report = {'source': str(source), 'working_copy': str(dest), 'replacement': str(replacement),
              'source_had_unsaved_changes': source_dirty,
              'component_before': component_name, 'component_after': updated.Name2,
              'replacement_verified': True, 'rebuild_ok': rebuild, 'transform_preserved': preserved,
              'mates_before': before_mates, 'mates_after': after_mates,
              'mate_count_preserved': before_mates == after_mates,
              'note': 'Mate count is not proof of correct attachment. Review geometry and mate errors. Working copy retains other original dependency references; not Pack and Go.'}
    report['mate_status'] = mate_status(copied)
    if not copied.Save3(1, error, warning) or error.value:
        raise RuntimeError('Replacement copy save failed')
    report['interference'] = interference(copied, stage)
    report['source_file_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report['source_reference_unchanged'] = Path(get(find(model), 'GetPathName')) == Path(expected_path)
    Path(str(dest)+'.replacement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return report


def pack_inventory(model, stage, signature_only=False):
    import pythoncom
    import win32com.client
    extension = model.Extension
    if signature_only:
        info = extension._oleobj_.GetTypeInfo()
        matches = []
        for index in range(info.GetTypeAttr()[6]):
            desc = info.GetFuncDesc(index)
            name = info.GetDocumentation(desc[0])[0]
            if name in ('GetPackAndGo', 'SavePackAndGo'):
                matches.append({'name': name, 'signature': repr(desc)})
        return {'interface': info.GetDocumentation(-1)[0], 'members': matches}
    extension._FlagAsMethod('GetPackAndGo')
    stage('reading_pack_and_go_inventory')
    package = extension.GetPackAndGo()
    if package is None:
        raise RuntimeError('Pack and Go unavailable')
    package._FlagAsMethod('GetDocumentNames')
    names = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
    accepted = package.GetDocumentNames(names)
    if not accepted:
        raise RuntimeError('Pack and Go inventory rejected')
    return {'document': get(model, 'GetPathName'), 'files': list(names.value or []),
            'count': int(get(package, 'GetDocumentNamesCount')), 'saved': False}


def interference(model, stage):
    if int(get(model, 'GetType')) != 2:
        raise ValueError('Assembly required')
    components = list(model.GetComponents(False) or [])
    excluded = []
    unresolved = []
    for component in components:
        state = int(get(component, 'GetSuppression'))
        row = {'name': component.Name2, 'path': get(component, 'GetPathName'), 'suppression': state}
        if state == 0:
            excluded.append(row)
        elif get(component, 'GetModelDoc2') is None:
            unresolved.append(row)
    if unresolved:
        return {'checked': False, 'unresolved_components': unresolved,
                'excluded_suppressed': excluded,
                'note': 'Resolve active components before checking. No component state was changed.'}
    manager = model.InterferenceDetectionManager
    if manager is None:
        raise RuntimeError('Interference manager unavailable')
    options = {'TreatCoincidenceAsInterference': False,
               'ShowIgnoredInterferences': True,
               'TreatSubAssembliesAsComponents': False,
               'IncludeMultibodyPartInterferences': True,
               'IgnoreHiddenBodies': False}
    previous = {key: get(manager, key) for key in options}
    try:
        for key, value in options.items():
            setattr(manager, key, value)
        stage('calculating_interferences', {'components': len(components), 'options': options})
        items = list(get(manager, 'GetInterferences') or [])
        count = int(get(manager, 'GetInterferenceCount'))
        rows = []
        for item in items:
            rows.append({'volume_m3': float(get(item, 'Volume')),
                         'ignored': bool(get(item, 'Ignore')),
                         'possible_interference': bool(get(item, 'IsPossibleInterference')),
                         'components': [{'name': c.Name2, 'path': get(c, 'GetPathName')}
                                        for c in get(item, 'Components') or []]})
        if count != len(rows):
            raise RuntimeError(f'Interference count mismatch: API {count}, returned {len(rows)}')
        return {'checked': True, 'document': get(model, 'GetPathName'),
                'count': count, 'interferences': rows, 'options': options,
                'excluded_suppressed': excluded,
                'scope': 'Active resolved assembly geometry, including hidden bodies; coincident contact excluded.',
                'note': 'Overlapping volumes do not by themselves establish an assembly defect; review intentional fits.'}
    finally:
        try:
            for key, value in previous.items():
                setattr(manager, key, value)
        finally:
            get(manager, 'Done')

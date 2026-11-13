"""Scoped, conservative document recycling inside an ALREADY serialized COM job.

No attachment, SaveAll, CloseAll, process kill, GC-as-memory-recovery, or force close.
Only exact task-owned paths with verified saved hashes can be closed. Dirty referenced
children block their parent even when the parent itself has a clean save flag.
"""
from __future__ import annotations
import gc
import hashlib
import ntpath
from pathlib import Path

def key(path):
    return ntpath.normcase(ntpath.abspath(path)) if path else ''

def member(obj, name, *args):
    value = getattr(obj, name)
    return value(*args) if args or (callable(value) and not hasattr(value, '_oleobj_')) else value

def snapshot_windows(sw):
    """Actual model windows, not the much larger list of loaded component documents.

    IFrame.ModelWindows/IModelWindow.ModelDoc verified in the installed 34.0 type library.
    Call only in an idle, serialized and responsive CAD session.
    """
    frame = member(sw, 'IFrameObject')
    windows = list(member(frame, 'ModelWindows') or [])
    if len(windows) != int(member(frame, 'GetModelWindowCount')):
        raise RuntimeError('Model-window inventory is incomplete')
    return [{'title': member(x, 'Title'), 'path': member(member(x, 'ModelDoc'), 'GetPathName')}
            for x in windows]

def assert_task_window_budget(sw, owned_paths, opening_path=None, limit=2):
    owned = {key(p) for p in owned_paths}
    windows = snapshot_windows(sw)
    current = [x for x in windows if key(x['path']) in owned]
    already_open = opening_path and any(key(x['path'])==key(opening_path) for x in windows)
    projected = len(current) + (0 if already_open else 1)
    if projected > limit:
        raise RuntimeError(f'Task window budget {limit} exceeded; recycle completed windows before opening another: {current}')
    return {'task_windows':len(current),'projected_task_windows':projected,'limit':limit,'all_windows':windows}

def snapshot_documents(sw):
    rows = []
    for doc in member(sw, 'GetDocuments') or []:
        path = member(doc, 'GetPathName')
        dirty = member(doc, 'GetSaveFlag')
        row = {'path': path, 'title': member(doc, 'GetTitle'),
               'type': int(member(doc, 'GetType')), 'dirty': bool(dirty) if isinstance(dirty,(bool,int)) and dirty in (0,1) else None,
               'dependencies': [], 'dependencies_known': False}
        try:
            if not path:
                raise ValueError('unsaved document has no stable path')
            raw = list(sw.GetDocumentDependencies2(path, True, True, False) or [])
            if len(raw) % 2:
                raise ValueError('ambiguous dependency inventory')
            row['dependencies'] = list(dict.fromkeys(raw[1::2]))
            if row['type'] == 2:
                # Include loaded/virtual/unsaved children that a file-based graph could miss.
                for c in doc.GetComponents(False) or []:
                    child = member(c, 'GetModelDoc2')
                    if child:
                        cp = member(child, 'GetPathName')
                        if not cp or not Path(cp).is_file():
                            raise ValueError('virtual/unsaved child; preserve parent')
                        if cp not in row['dependencies']: row['dependencies'].append(cp)
            row['dependencies_known'] = True
        except Exception as exc:
            row['dependency_error'] = str(exc)
        rows.append(row)
    return rows

def plan_recycle(documents, manifest, keep=()):
    """Pure policy. Manifest: task_id + documents[{path, completed, sha256}]."""
    if not manifest.get('task_id'):
        raise ValueError('Task ownership identity required')
    owned = {key(x['path']): x for x in manifest['documents']}
    loaded = {key(x['path']): x for x in documents if x['path']}
    keep = {key(p) for p in keep}
    protected = set(keep)
    for p in keep:
        if p in loaded: protected.update(key(d) for d in loaded[p]['dependencies'])
    result = []
    for doc in documents:
        p = key(doc['path'])
        if p not in owned: continue
        closure = {p} | {key(d) for d in doc['dependencies']}
        reason = None
        if not doc['dependencies_known']: reason = 'dependency inventory unknown'
        elif closure & protected: reason = 'needed by retained document'
        elif any(key(other['path']) not in closure and p in {key(d) for d in other['dependencies']}
                 for other in documents): reason = 'referenced by another loaded document'
        elif any(c not in owned for c in closure if c in loaded): reason = 'loaded dependency not owned by this task'
        elif any(loaded[c]['dirty'] is not False for c in closure if c in loaded): reason = 'unsaved or unknown parent/referenced-child state'
        elif any(not owned[c].get('completed') or len(owned[c].get('sha256', '')) != 64
                 for c in closure if c in loaded): reason = 'saved checkpoint not verified'
        elif sum(x['title'].casefold() == doc['title'].casefold() for x in documents) != 1:
            reason = 'ambiguous CloseDoc title'
        result.append({'path': doc['path'], 'title': doc['title'], 'close': reason is None,
                       'reason': reason, 'loaded_closure': [loaded[c]['path'] for c in closure if c in loaded]})
    # Parent assemblies/drawings first; never attempt to close all component windows.
    return sorted(result, key=lambda x: (0 if loaded[key(x['path'])]['type'] in (2, 3) else 1, x['path']))

def recycle_completed(sw, manifest, keep=(), dry_run=True):
    """Caller holds the CAD lock and confirmed session is responsive. Returns evidence."""
    initial = snapshot_documents(sw)
    plan = plan_recycle(initial, manifest, keep)
    report = {'dry_run': dry_run, 'loaded_before': len(initial), 'plan': plan, 'closed': [], 'retained': []}
    if dry_run:
        report['retained'] = [x for x in plan if not x['close']]
        return report
    owned = {key(x['path']): x for x in manifest['documents']}
    for candidate in plan:
        if not candidate['close']: continue
        # Refresh after EVERY parent close; shared dependencies and dirty flags may change.
        live = snapshot_documents(sw)
        fresh = next((x for x in plan_recycle(live, manifest, keep) if key(x['path'])==key(candidate['path'])), None)
        if fresh is None: continue
        if not fresh['close']:
            report['retained'].append(fresh); continue
        mismatched = [p for p in fresh['loaded_closure']
                      if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=owned[key(p)]['sha256']]
        if mismatched:
            report['retained'].append({'path': fresh['path'], 'reason': 'saved checkpoint changed', 'files': mismatched}); continue
        sw.CloseDoc(fresh['title'])
        after = snapshot_documents(sw)
        if any(key(x['path'])==key(fresh['path']) for x in after):
            report['retained'].append({'path': fresh['path'], 'reason': 'still loaded after CloseDoc'})
            break
        report['closed'].append(fresh['path'])
    gc.collect()  # Release Python references only; not a substitute for CloseDoc.
    final = snapshot_documents(sw)
    report['loaded_after'] = len(final)
    # Report every owned document still loaded, including those excluded by the
    # initial plan. Recompute after closing parents: their children may already
    # have unloaded, so the original plan is not a final inventory.
    execution_reasons = {key(x['path']): x for x in report['retained']}
    report['retained'] = []
    for item in plan_recycle(final, manifest, keep):
        if key(item['path']) in execution_reasons:
            report['retained'].append(execution_reasons[key(item['path'])])
        else:
            report['retained'].append({
                **item, 'close': False,
                'reason': item['reason'] or 'cleanup stopped before this document was closed',
            })
    return report

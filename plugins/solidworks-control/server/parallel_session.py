"""Exact ROT/PID binding for isolated sessions; never fall back to ActiveObject."""
import sys
from pathlib import Path
import psutil

SKILL = Path(__file__).resolve().parent/'helpers'

def identity(pid, created):
    p = psutil.Process(int(pid))
    if p.name().casefold() != 'sldworks.exe' or p.num_threads() == 0 or p.create_time() != float(created):
        raise RuntimeError('SolidWorks PID/creation identity is stale or wrong')
    return p

def connect(pid, created):
    import pythoncom, win32com.client
    identity(pid, created)
    rot = pythoncom.GetRunningObjectTable(); ctx = pythoncom.CreateBindCtx(0)
    expected = f'SolidWorks_PID_{int(pid)}'; matches = []
    for moniker in rot.EnumRunning():
        try: name = moniker.GetDisplayName(ctx, None)
        except pythoncom.com_error: continue
        if name == expected: matches.append(moniker)
    if len(matches) != 1:
        raise RuntimeError(f'Exact ROT registration unavailable: {expected}; no fallback allowed')
    sw = win32com.client.Dispatch(rot.GetObject(matches[0]).QueryInterface(pythoncom.IID_IDispatch))
    value = sw.GetProcessID
    if int(value() if callable(value) else value) != int(pid):
        raise RuntimeError('COM GetProcessID does not match requested session')
    identity(pid, created)
    return sw

def resources(pid=None, created=None):
    """Keep the existing numerical memory policy, account for ALL instances."""
    sys.path.insert(0, str(SKILL))
    from sw_performance import memory_snapshot, evaluate_memory
    if pid is not None: identity(pid, created)
    sample = memory_snapshot()
    # Identity ambiguity is resolved by exact ROT binding, not by erasing memory.
    # Evaluate memory with one aggregate row so all private bytes remain counted.
    aggregate = dict(sample)
    aggregate['solidworks'] = [{'private_bytes': sum(p['private_bytes'] for p in sample['solidworks']), 'thread_count': 1}]
    result = evaluate_memory(aggregate)
    result['sample'] = sample
    result['scope'] = 'Explicit PID identity; unchanged RAM thresholds; all SW private bytes counted'
    if not result['allowed']: raise RuntimeError('Parallel resource admission blocked: ' + str(result))
    return result

"""Bind one live SW session by ROT identity; retain and never terminate process remnants."""
import pythoncom, win32com.client, psutil

def member(obj,name):
    value=getattr(obj,name)
    return value() if callable(value) else value

def connect_existing():
    processes=[p for p in psutil.process_iter(['name']) if str(p.info['name']).lower()=='sldworks.exe']
    live=[p for p in processes if p.num_threads()>0]
    if len(live)!=1:
        raise RuntimeError(f'Expected exactly one SW process with threads; found {len(live)}. No ambiguous connection allowed.')
    target=live[0];created=target.create_time();expected=f'SolidWorks_PID_{target.pid}'
    rot=pythoncom.GetRunningObjectTable();ctx=pythoncom.CreateBindCtx(0);matches=[]
    for moniker in rot.EnumRunning():
        try:name=moniker.GetDisplayName(ctx,None)
        except pythoncom.com_error:continue
        if name.startswith('SolidWorks_PID_'):matches.append((name,moniker))
    if matches:
        if len(matches)!=1 or matches[0][0]!=expected:
            raise RuntimeError('SolidWorks ROT identities do not match the unique live process')
        sw=win32com.client.Dispatch(rot.GetObject(matches[0][1]).QueryInterface(pythoncom.IID_IDispatch))
    elif len(processes)==1:
        sw=win32com.client.GetActiveObject('SldWorks.Application')
    else:
        raise RuntimeError('Multiple process records require one exact matching ROT-PID registration')
    if int(member(sw,'GetProcessID'))!=target.pid or target.create_time()!=created:
        raise RuntimeError('SolidWorks COM PID/creation identity changed during binding')
    # Recheck all process records after binding; an additional initializing session blocks work.
    current=[p for p in psutil.process_iter(['name']) if str(p.info['name']).lower()=='sldworks.exe' and p.num_threads()>0]
    if len(current)!=1 or current[0].pid!=target.pid:
        raise RuntimeError('SolidWorks process set changed during binding')
    return sw

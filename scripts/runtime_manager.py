"""Install isolated MCP runtimes and inspect dependencies without opening CAD files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.1.0'
NODE_VERSION='24.22.1'
SERVERS={
 'solidworks_local':dict(plugin='solidworks-control', requirements='server/requirements-lock.txt', include=['server'], entry='server/server.py', windows=True),
 'kicad':dict(plugin='kicad-control',requirements='server/requirements.lock.txt',include=['server'],entry='server/kicad_mcp_local.py'),
 'blender_official':dict(plugin='blender-control',requirements='server/requirements.lock',include=['server'],module='blmcp',cwd='server/mcp'),
 'lighttools':dict(plugin='lighttools-control',requirements='requirements.lock',include=['lighttools_control','run_server.py','requirements.lock'],entry='run_server.py',windows=True),
 'zemax':dict(plugin='zemax-control',requirements='requirements-lock.txt',include=['zemax_mcp','scripts/run_server.py','requirements-lock.txt'],entry='scripts/run_server.py',windows=True),
 'rea':dict(plugin='rea-control',include=['runtime/package.json','runtime/package-lock.json'],node=True),
}

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as f:
        json.dump(data,f,ensure_ascii=False,indent=2);temporary=Path(f.name)
    os.replace(temporary,path)

def safe_outside_repo(path):
    path=Path(path).expanduser().resolve()
    if path==ROOT or path.is_relative_to(ROOT):raise ValueError('Runtime/config/data must live outside the repository')
    return path

def source_files(spec):
    package=ROOT/'plugins'/spec['plugin']
    files=[]
    for name in spec['include']:
        p=package/name
        if p.is_file():files.append(p);continue
        for base,dirs,names in os.walk(p):
            dirs[:]=[d for d in dirs if d not in ['__pycache__','build'] and not d.endswith('.egg-info')]
            files.extend(Path(base,n) for n in names)
    if not files:raise ValueError('Missing bundled runtime source: '+spec['plugin'])
    return package,sorted(files)

def fingerprint(spec):
    root,files=source_files(spec);h=hashlib.sha256()
    for f in files:
        h.update(f.relative_to(root).as_posix().encode());h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()

def run(command, log, cwd=None):
    with Path(log).open('ab') as f:
        result=subprocess.run(command,cwd=cwd,stdout=f,stderr=f)
    if result.returncode:raise RuntimeError('Dependency command failed; see local log '+str(log))

def node_supported(version):
    parts=tuple(map(int,version.lstrip('v').split('.')[:3]))
    return (parts[0]==22 and parts>=(22,23,4)) or (parts[0]==24 and parts>=(24,22,1)) or parts>=(26,12,1)

def ensure_node(base):
    node=shutil.which('node')
    if node:
        v=subprocess.check_output([node,'--version'],text=True).strip().lstrip('v')
        if node_supported(v):return Path(node)
    if platform.system()!='Windows' or platform.machine().lower() not in ['amd64','x86_64']:
        raise RuntimeError('Install Node.js 24.22.1+ (24.x) or >=26.12.1 with npm, then retry')
    folder=base/f'node-v{NODE_VERSION}-win-x64';node=folder/'node.exe'
    if node.is_file():return node
    base.mkdir(parents=True,exist_ok=True)
    name=f'node-v{NODE_VERSION}-win-x64.zip';url=f'https://nodejs.org/dist/v{NODE_VERSION}/'
    sums=urllib.request.urlopen(url+'SHASUMS256.txt',timeout=40).read().decode()
    matches=[line.split()[0] for line in sums.splitlines() if line.split()[-1]==name]
    if len(matches)!=1:raise RuntimeError('No unique official Node SHA256')
    with tempfile.TemporaryDirectory(prefix='personal-node-') as t:
        archive=Path(t)/name
        with urllib.request.urlopen(url+name,timeout=60) as response,archive.open('wb') as output:shutil.copyfileobj(response,output)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=matches[0]:raise RuntimeError('Node checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                dest=(base/member.filename).resolve()
                if not dest.is_relative_to(base.resolve()) or ((member.external_attr>>16)&0o170000)==0o120000:raise RuntimeError('Unsafe Node archive entry')
            z.extractall(base)
    return node

def install_server(name,base,repair=False):
    spec=SERVERS[name]
    if spec.get('windows') and os.name!='nt':return None,'unsupported_platform'
    digest=fingerprint(spec);folder=base/VERSION/(name+'-'+digest[:12]);folder.mkdir(parents=True,exist_ok=True)
    mark=folder/'installed.json';source=folder/'source';log=folder/'install.log'
    cached=json.loads(mark.read_text(encoding='utf8')) if mark.is_file() else None
    if not repair and cached and cached.get('source_sha256')==digest and Path(cached['record']['command']).is_file():
        if name=='blender_official':create_addon_archive(folder,source)
        return cached['record'],'already_installed'
    package,files=source_files(spec)
    for f in files:
        target=source/f.relative_to(package);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
    if spec.get('node'):
        node=ensure_node(base/'node');npm=node.parent/'node_modules/npm/bin/npm-cli.js'
        if not npm.is_file():
            npmcmd=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
            if not npmcmd:raise RuntimeError('Node exists but npm is missing')
            npm_command=[npmcmd]
        else:npm_command=[str(node),str(npm)]
        run([*npm_command,'ci','--omit=dev','--ignore-scripts','--no-audit','--no-fund'],log,cwd=source/'runtime')
        record={'command':str(node),'args':[str(source/'runtime/node_modules/rea-agents/scripts/rea.mjs'),'mcp'],'cwd':str(folder)}
    else:
        envdir=folder/'venv';python=envdir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not python.is_file():run([sys.executable,'-m','venv',str(envdir)],log)
        command=[str(python),'-m','pip','install','--disable-pip-version-check','--retries','2','--timeout','30','-r',str(source/spec['requirements'])]
        if repair:command.append('--force-reinstall')
        run(command,log)
        run([str(python),'-m','pip','check'],log)
        args=['-m',spec['module']] if 'module' in spec else [str(source/spec['entry'])]
        record={'command':str(python),'args':args,'cwd':str(source/spec['cwd']) if 'cwd' in spec else str(folder)}
    record.update(managed_by='codex-personal-capabilities',release=VERSION,source_sha256=digest,env={'PYTHONUTF8':'1','PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1','PERSONAL_MCP_DATA':str(base/'private-data')})
    if name=='blender_official':record['env'].update(BLENDER_MCP_HOST='127.0.0.1',BLENDER_MCP_PORT='9876')
    if name=='rea':record['env'].update(REA_MCP_INPUT_SCHEMA_PROFILE='compact',REA_MCP_OUTPUT_SCHEMA_PROFILE='off')
    if name=='blender_official':create_addon_archive(folder,source)
    write_json(mark,{'source_sha256':digest,'record':record})
    return record,'installed'

def create_addon_archive(folder,source):
    addon=source/'server/addon/blender_mcp_addon'
    with zipfile.ZipFile(folder/'blender-mcp-addon.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in addon.rglob('*'):
            if file.is_file():archive.write(file,file.relative_to(addon).as_posix())

def native_discovery():
    """Executable/path presence only. No app launch and no license validation."""
    candidates=[Path(os.environ.get('ProgramFiles','C:/Program Files')),Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))]
    locations=[Path(value) for key,value in os.environ.items() if re.fullmatch(r'AWP_ROOT\d+',key) and value]
    if os.name=='nt':
        import winreg
        for hive in [winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER]:
            for view in [winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY]:
                try:
                    with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',0,winreg.KEY_READ|view) as parent:
                        for i in range(winreg.QueryInfoKey(parent)[0]):
                            try:
                                with winreg.OpenKey(parent,winreg.EnumKey(parent,i)) as key:
                                    name=winreg.QueryValueEx(key,'DisplayName')[0]
                                    if not re.search(r'Blender|KiCad|SOLIDWORKS|LightTools|Zemax|Ansys',name,re.I):continue
                                    value=winreg.QueryValueEx(key,'InstallLocation')[0]
                                    if value:locations.append(Path(value.strip('"')))
                            except OSError:pass
                except OSError:pass
    def find(env, exe, suffixes):
        supplied=os.environ.get(env)
        if supplied:return supplied if Path(supplied).is_file() else None
        direct=shutil.which(exe)
        if direct:return direct
        for root in locations+candidates:
            for pattern in suffixes:
                for f in sorted(root.glob(pattern),reverse=True):
                    if f.is_file():return str(f)
        return None
    found={
        'BLENDER_PATH':find('BLENDER_PATH','blender',['blender.exe','Blender Foundation/Blender */blender.exe']),
        'KICAD_CLI':find('KICAD_CLI','kicad-cli',['bin/kicad-cli.exe','KiCad/*/bin/kicad-cli.exe']),
        'SOLIDWORKS_EXE':find('SOLIDWORKS_EXE','SLDWORKS.exe',['SLDWORKS.exe','SOLIDWORKS/SLDWORKS.exe','SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe']),
        'LIGHTTOOLS_EXE':find('LIGHTTOOLS_EXE','lt.exe',['lt.exe','Optical Research Associates/LightTools */lt.exe']),
        'ZEMAX_EXE':find('ZEMAX_EXE','OpticStudio.exe',['OpticStudio.exe','Zemax OpticStudio/OpticStudio.exe','ANSYS Inc/v*/Zemax OpticStudio/OpticStudio.exe'])}
    return found

def discovery_env(name,found):
    env={}
    if name=='blender_official' and found['BLENDER_PATH']:env['BLENDER_PATH']=found['BLENDER_PATH']
    if name=='kicad' and found['KICAD_CLI']:
        path=Path(found['KICAD_CLI']).parent.parent/'share/kicad/symbols'
        if path.is_dir():env['KICAD_SYMBOL_DIR']=str(path)
    if name=='lighttools' and found['LIGHTTOOLS_EXE']:env['LIGHTTOOLS_HOME']=str(Path(found['LIGHTTOOLS_EXE']).parent)
    if name=='solidworks_local' and found['SOLIDWORKS_EXE']:
        p=Path(found['SOLIDWORKS_EXE']);env['SOLIDWORKS_EXE']=str(p)
        if (p.parent/'swconst.tlb').is_file():env['SOLIDWORKS_TLB']=str(p.parent/'swconst.tlb')
        flow=p.parent.parent/'SOLIDWORKS Flow Simulation'
        if flow.is_dir():env['SOLIDWORKS_FLOW_HOME']=str(flow)
        common=Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'SOLIDWORKS'
        templates=[q for q in common.glob('SOLIDWORKS */templates') if (q/'gb_part.prtdot').is_file()]
        if len(templates)==1:env['SOLIDWORKS_TEMPLATES']=str(templates[0])
    for key in ['SOLIDWORKS_EXE','SOLIDWORKS_TLB','SOLIDWORKS_TEMPLATES','SOLIDWORKS_FLOW_HOME','KICAD_SYMBOL_DIR','ZEMAX_ROOT','BLENDER_PATH','LIGHTTOOLS_HOME']:
        if os.environ.get(key):env[key]=os.environ[key]
    return env

def probe(record,timeout=35):
    """Only initialize and tools/list: never invokes a native tool."""
    lines=queue.Queue();errors=[]
    child=subprocess.Popen([record['command'],*record.get('args',[])],cwd=record.get('cwd'),env={**os.environ,**record.get('env',{})},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',errors='replace',bufsize=1)
    def reader():
        for line in child.stdout:lines.put(line)
        lines.put(None)
    def stderr_reader():
        for line in child.stderr:
            errors.append(line[-1000:]);errors[:]=errors[-8:]
    threading.Thread(target=reader,daemon=True).start();threading.Thread(target=stderr_reader,daemon=True).start()
    def send(data):child.stdin.write(json.dumps(data)+'\n');child.stdin.flush()
    def response(wanted):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:line=lines.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:break
            if line is None:raise RuntimeError('MCP process exited before response: '+''.join(errors)[-1200:])
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('id')==wanted:
                if 'error' in value:raise RuntimeError('MCP returned a protocol error')
                return value['result']
        raise TimeoutError('MCP response timed out')
    try:
        send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'personal-runtime-doctor','version':VERSION}}})
        response(1);send({'jsonrpc':'2.0','method':'notifications/initialized'})
        count=0;cursor=None;seen=set();request_id=2
        while True:
            send({'jsonrpc':'2.0','id':request_id,'method':'tools/list','params':{'cursor':cursor} if cursor else {}})
            result=response(request_id);count+=len(result.get('tools',[]));cursor=result.get('nextCursor')
            if not cursor:break
            if cursor in seen or request_id>100:raise RuntimeError('Invalid tools/list pagination')
            seen.add(cursor);request_id+=1
        if not count:raise RuntimeError('MCP returned no tools')
        return {'status':'ready','tools':count,'native_operations':'not_called'}
    finally:
        child.stdin.close()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name=='nt':
                # Only this doctor's own spawned process tree; no CAD tools were called.
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:child.kill()
            child.wait(timeout=5)
        child.stdout.close();child.stderr.close()

def merge_config(existing,records,replace=False):
    result={**existing,'servers':dict(existing.get('servers',{}))};preserved=[]
    for name,value in records.items():
        old=result['servers'].get(name)
        if old and old.get('managed_by')!='codex-personal-capabilities' and not replace:preserved.append(name);continue
        if old:
            env={**value.get('env',{}),**old.get('env',{})}
            # Runtime defaults follow the release; software paths and private overrides remain local.
            for key in ['PYTHONUTF8','PYTHONUNBUFFERED','PYTHONDONTWRITEBYTECODE','REA_MCP_INPUT_SCHEMA_PROFILE','REA_MCP_OUTPUT_SCHEMA_PROFILE']:
                if key in value.get('env',{}):env[key]=value['env'][key]
            value={**value,'env':env}
        result['servers'][name]=value
    return result,preserved

def doctor(config,selected):
    found=native_discovery();results={}
    for name in selected:
        if SERVERS[name].get('windows') and os.name!='nt':results[name]={'status':'unsupported_platform'};continue
        record=config.get('servers',{}).get(name)
        if not record:results[name]={'status':'not_configured'};continue
        try:results[name]=probe(record)
        except (OSError,ValueError,RuntimeError,TimeoutError) as error:results[name]={'status':'failed','error':str(error)}
    requirements={'solidworks_local':'SOLIDWORKS_EXE','blender_official':'BLENDER_PATH','kicad':'KICAD_CLI','lighttools':'LIGHTTOOLS_EXE','zemax':'ZEMAX_EXE'}
    for name,result in results.items():
        if name in requirements:
            present=found.get(requirements[name]);result['native_software']='detected_not_exercised' if present else 'missing_or_not_discovered'
    return {'release':VERSION,'services':results,'native_software':found,'licenses':'not_checked','blender_addon':'Install/enable the generated blender-mcp-addon.zip in Blender; tools/list does not test the addon socket.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','doctor']);p.add_argument('--servers',nargs='+',choices=list(SERVERS),default=list(SERVERS));p.add_argument('--runtime-root',default=str(Path.home()/'.codex/personal-runtimes'));p.add_argument('--config',default=str(Path.home()/'.codex/personal-runtime.json'));p.add_argument('--replace-existing',action='store_true');p.add_argument('--repair',action='store_true');p.add_argument('--report');a=p.parse_args()
    base=safe_outside_repo(a.runtime_root);config=safe_outside_repo(a.config)
    existing=json.loads(config.read_text(encoding='utf8')) if config.is_file() else {}
    if a.action=='install':
        if sys.version_info<(3,11):raise SystemExit('Python 3.11+ is required')
        records={};found=native_discovery()
        for name in a.servers:
            print('Installing:',name,flush=True);record,status=install_server(name,base,a.repair);print(name,status,flush=True)
            if record:
                record['env'].update(discovery_env(name,found))
                if name=='rea':record['env'].update(REA_MCP_INPUT_SCHEMA_PROFILE='compact',REA_MCP_OUTPUT_SCHEMA_PROFILE='off')
                records[name]=record
        merged,preserved=merge_config(existing,records,a.replace_existing)
        if merged!=existing:
            if config.is_file():shutil.copyfile(config,config.with_suffix('.previous.json'))
            write_json(config,merged)
        existing=merged
        if preserved:print('Existing custom server config preserved:',', '.join(preserved))
    report=doctor(existing,a.servers);target=safe_outside_repo(a.report) if a.report else base/'doctor.json';write_json(target,report)
    for name,result in report['services'].items():print(name,result['status'],result.get('tools',''),result.get('native_software',''))
    print('Local report:',target,'; licenses are not checked.')
    return 1 if any(x['status'] in ['failed','not_configured'] for x in report['services'].values()) else 0

if __name__=='__main__':raise SystemExit(main())

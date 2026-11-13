"""Install the checked-out release using the official Codex plugin CLI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os
import runtime_manager

ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--plugins',nargs='*',help='Install only these packages; default installs all')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--skills-only',action='store_true',help='Skip native MCP environment setup')
    p.add_argument('--runtime-root',default=str(Path.home()/'.codex/personal-runtimes'))
    p.add_argument('--config',default=str(Path.home()/'.codex/personal-runtime.json'))
    a=p.parse_args()
    codex=shutil.which('codex')
    if not codex:raise SystemExit('Install Codex CLI / desktop CLI and add codex to PATH first.')
    subprocess.run([sys.executable,str(ROOT/'scripts/validate.py')],check=True)
    market=json.loads((ROOT/'.agents/plugins/marketplace.json').read_text(encoding='utf8'))
    names=[x['name'] for x in market['plugins']]
    selected=names if a.plugins is None else a.plugins
    if any(n not in names for n in selected):raise SystemExit('Unknown plugin selection')
    if os.environ.get('CODEX_HOME') and not a.dry_run:
        runtime_manager.safe_outside_repo(os.environ['CODEX_HOME']).mkdir(parents=True,exist_ok=True)
    servers=[name for name,spec in runtime_manager.SERVERS.items() if spec['plugin'] in selected]
    if servers and not a.skills_only:
        command=[sys.executable,str(ROOT/'scripts/runtime_manager.py'),'install','--runtime-root',a.runtime_root,'--config',a.config,'--servers',*servers]
        if a.dry_run:print(json.dumps(command))
        else:subprocess.run(command,check=True)
    commands=[[codex,'plugin','marketplace','add',str(ROOT)]]
    commands.extend([codex,'plugin','add',n+'@'+market['name'],'--json'] for n in selected)
    for command in commands:
        if a.dry_run:print(json.dumps(command,ensure_ascii=False))
        elif '--json' in command:
            output=subprocess.check_output(command,text=True,encoding='utf8')
            installed=Path(json.loads(output)['installedPath']).resolve()
            # Official CLI supplies the cache path. Only adapt the installed template,
            # never put machine paths into this Git repository.
            metadata=json.loads((installed/'.codex-plugin/plugin.json').read_text(encoding='utf8'))
            if metadata['name']!=command[3].split('@')[0]:raise RuntimeError('Installed plugin identity mismatch')
            config_file=installed/'.mcp.json'
            if config_file.is_file():
                mcp=json.loads(config_file.read_text(encoding='utf8'))
                if a.skills_only:mcp['mcpServers']={}
                if os.name!='nt':
                    mcp['mcpServers']={k:v for k,v in mcp['mcpServers'].items() if not runtime_manager.SERVERS.get(k,{}).get('windows')}
                for entry in mcp['mcpServers'].values():
                    entry['command']=sys.executable
                    entry['env']={**entry.get('env',{}),'PERSONAL_RUNTIME_CONFIG':str(runtime_manager.safe_outside_repo(a.config))}
                runtime_manager.write_json(config_file,mcp)
            print('Installed:',metadata['name'])
        else:subprocess.run(command,check=True)
    print('Installed. Start a new Codex chat. See the runtime doctor for software/license/addon readiness.')

if __name__=='__main__':main()

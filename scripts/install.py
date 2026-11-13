"""Install the checked-out release using the official Codex plugin CLI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--plugins',nargs='*',help='Install only these packages; default installs all')
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    codex=shutil.which('codex')
    if not codex:raise SystemExit('Install Codex CLI / desktop CLI and add codex to PATH first.')
    subprocess.run([sys.executable,str(ROOT/'scripts/validate.py')],check=True)
    market=json.loads((ROOT/'.agents/plugins/marketplace.json').read_text(encoding='utf8'))
    names=[x['name'] for x in market['plugins']]
    selected=names if a.plugins is None else a.plugins
    if any(n not in names for n in selected):raise SystemExit('Unknown plugin selection')
    commands=[[codex,'plugin','marketplace','add',str(ROOT)]]
    commands.extend([codex,'plugin','add',n+'@'+market['name']] for n in selected)
    for command in commands:
        if a.dry_run:print(json.dumps(command,ensure_ascii=False))
        else:subprocess.run(command,check=True)
    print('Installed. Start a new Codex chat. Configure native runtimes separately (RUNTIMES.md).')

if __name__=='__main__':main()

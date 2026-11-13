"""Fail closed on manifest drift, known credentials, and private generated files."""
import hashlib
import json
from pathlib import Path
import re
import sys
import os

ROOT=Path(__file__).resolve().parents[1]
SECRET=re.compile(r'(?<![\w-])(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|sk-[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
FORBIDDEN={'.env','auth.json','credentials.json','personal-runtime.json','config.toml'}
SUFFIX={'.sqlite','.sqlite3','.db','.jsonl','.log','.pem','.key','.pfx','.pyc','.zmx','.zos','.sldprt','.sldasm','.blend','.drwdot','.slddrt'}

def files(root):
    for base,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in ['.git','__pycache__'] and Path(base,d).relative_to(root).as_posix()!='plugins/blender-control/server/mcp/build']
        for name in names:yield Path(base,name)

def problems(root=ROOT):
    errors=[]
    for f in files(root):
        rel=f.relative_to(root)
        if '.git' in rel.parts or '__pycache__' in rel.parts:continue
        if f.is_symlink():errors.append(str(rel)+': symlink');continue
        if not f.is_file():continue
        if f.name in FORBIDDEN or f.name.startswith('.env.') or f.suffix.lower() in SUFFIX:errors.append(str(rel)+': forbidden file')
        try:s=f.read_text(encoding='utf8')
        except UnicodeDecodeError:errors.append(str(rel)+': unreviewed binary');continue
        if SECRET.search(s):errors.append(str(rel)+': credential pattern')
        if re.search(r'[C-Z]:[\\/]+Users[\\/]+Administrator|E:[\\/]+(?:AGENT|工作区)|D:[\\/]+AI[\\/]',s):errors.append(str(rel)+': original machine/project path')
    return errors

def main():
    errors=problems()
    market=json.loads((ROOT/'.agents/plugins/marketplace.json').read_text(encoding='utf8'))
    for entry in market['plugins']:
        package=(ROOT/entry['source']['path']).resolve()
        if not package.is_relative_to(ROOT):errors.append('marketplace path escape');continue
        meta=json.loads((package/'.codex-plugin/plugin.json').read_text(encoding='utf8'))
        if meta['name']!=entry['name']:errors.append('manifest identity mismatch')
        if not meta.get('version') or not list((package/'skills').glob('*/SKILL.md')):errors.append('missing skills/version')
        for key in ['skills','mcpServers']:
            if key in meta and not (package/meta[key]).exists():errors.append('missing manifest resource: '+entry['name'])
        if (package/'.mcp.json').exists():
            for runtime in json.loads((package/'.mcp.json').read_text(encoding='utf8'))['mcpServers'].values():
                for arg in runtime.get('args',[]):
                    if arg.startswith('${PLUGIN_ROOT}/') and not (package/arg.removeprefix('${PLUGIN_ROOT}/')).is_file():errors.append('missing launcher')
    lock=ROOT/'files.sha256.json'
    if lock.exists():
        expected=json.loads(lock.read_text(encoding='utf8'))
        current={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files(ROOT) if p.is_file() and p!=lock}
        if expected!=current:errors.append('file integrity manifest mismatch: refresh intentionally before committing')
    if errors:
        print('\n'.join(errors),file=sys.stderr);return 1
    print(f"PASS: {len(market['plugins'])} plugins; source/privacy/manifest/integrity checks")
    return 0

if __name__=='__main__':raise SystemExit(main())

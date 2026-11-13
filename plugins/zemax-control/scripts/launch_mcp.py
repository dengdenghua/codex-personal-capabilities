"""Portable stdio launcher. Machine configuration is never stored in this repository."""
import json
import os
from pathlib import Path
import subprocess
import sys


def resolve(server, config_path=None):
    location = Path(config_path or os.environ.get('PERSONAL_RUNTIME_CONFIG') or Path.home() / '.codex' / 'personal-runtime.json')
    if not location.is_file():
        raise ValueError('Configure ~/.codex/personal-runtime.json on this computer; see RUNTIMES.md.')
    record = json.loads(location.read_text(encoding='utf-8-sig')).get('servers', {}).get(server)
    if not isinstance(record, dict):
        raise ValueError('Runtime is not configured for ' + server)
    command, args = record.get('command'), record.get('args', [])
    if not isinstance(command, str) or not command.strip() or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError('Runtime requires a command string and args string array')
    extra = record.get('env', {})
    if not isinstance(extra, dict) or not all(isinstance(k, str) and isinstance(v, str) for k,v in extra.items()):
        raise ValueError('Runtime env must map strings to strings')
    cwd = record.get('cwd')
    if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_dir()):
        raise ValueError('Configured runtime cwd does not exist')
    return [command, *args], {**os.environ, **extra}, cwd


def main():
    try:
        argv, env, cwd = resolve(sys.argv[1])
        # Argument arrays, no shell expansion. stdout belongs exclusively to MCP.
        return subprocess.call(argv, env=env, cwd=cwd)
    except (ValueError, OSError, IndexError):
        print('Personal MCP runtime unavailable or invalid. Configure it locally; see RUNTIMES.md.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

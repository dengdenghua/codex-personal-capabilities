import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'files.sha256.json'
files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts and p!=target}
target.write_text(json.dumps(files,indent=2,ensure_ascii=False)+'\n',encoding='utf8', newline='\n')
print('Locked',len(files),'files')

import hashlib
import json
from pathlib import Path
from validate import files as source_files
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'files.sha256.json'
files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_files(ROOT)) if p.is_file() and p!=target}
target.write_text(json.dumps(files,indent=2,ensure_ascii=False)+'\n',encoding='utf8', newline='\n')
print('Locked',len(files),'files')

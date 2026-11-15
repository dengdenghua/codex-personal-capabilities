"""Pinned upstream executables; never install them or credentials in this checkout."""
import bz2
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import urllib.request
import zipfile
from optics_private import outside, read, sha, write

ROOT=Path(__file__).resolve().parents[1]

def local_root():
    return Path(os.environ['LOCALAPPDATA'])/'CodexPrivateBackup' if os.name=='nt' else Path.home()/'.local/share/codex-private-backup'

def ensure_tools(root=None):
    root=outside(root or local_root()/'tools')
    architecture=platform.machine().lower()
    if architecture not in {'amd64','x86_64'} or platform.system() not in {'Windows','Linux'}:
        raise ValueError('Automatic cloud tool setup currently supports Windows/Linux x64')
    target=('windows' if os.name=='nt' else 'linux')+'-amd64'
    result={}
    for name,info in read(ROOT/'cloud-tools.json').items():
        spec=info[target];folder=root/(name+'-'+info['version'])/target
        binary=folder/(name+('.exe' if os.name=='nt' else ''))
        receipt=folder/'verified-tool.json'
        if receipt.exists():
            record=read(receipt)
            if record['archive_sha256']!=spec['sha256'] or not binary.is_file() or sha(binary)!=record['binary_sha256']:
                raise ValueError('Managed cloud tool changed; retain it for diagnosis and use a new tool directory')
        else:
            folder.mkdir(parents=True,exist_ok=True)
            download=folder/('upstream.zip' if 'member' in spec else 'upstream.bz2')
            if not download.exists():
                partial=download.with_suffix(download.suffix+'.partial')
                if partial.is_symlink():raise ValueError('Unexpected download link')
                request=urllib.request.Request(spec['url'],headers={'User-Agent':'Codex-Personal-Capabilities'})
                with urllib.request.urlopen(request,timeout=60) as source,partial.open('wb') as destination:
                    shutil.copyfileobj(source,destination,1024*1024)
                if sha(partial)!=spec['sha256']:raise ValueError('Upstream cloud tool SHA256 mismatch')
                os.replace(partial,download)
            if sha(download)!=spec['sha256']:raise ValueError('Upstream cloud tool SHA256 mismatch')
            if binary.exists():raise ValueError('Unverified executable already exists')
            output=binary.with_suffix(binary.suffix+'.partial')
            if output.is_symlink():raise ValueError('Unexpected executable link')
            if 'member' in spec:
                with zipfile.ZipFile(download) as archive,archive.open(spec['member']) as source,output.open('wb') as destination:
                    shutil.copyfileobj(source,destination,1024*1024)
            else:
                with bz2.open(download,'rb') as source,output.open('wb') as destination:
                    shutil.copyfileobj(source,destination,1024*1024)
            os.replace(output,binary)
            if os.name!='nt':binary.chmod(0o700)
            write(receipt,{'version':info['version'],'archive_sha256':spec['sha256'],'binary_sha256':sha(binary)})
        result[name]=str(binary)
    return result

if __name__=='__main__':
    print(json.dumps(ensure_tools(),indent=2))

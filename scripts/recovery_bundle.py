"""Encrypt or unlock an offline recovery bundle; passphrase is entered locally."""
import argparse, getpass, io, secrets, zipfile
from pathlib import Path
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import optics_cloud as cloud

MAGIC=b'ECHO-RECOVERY-1\0'
def key(password,salt):
    return Scrypt(salt=salt,length=32,n=2**16,r=8,p=1).derive(password.encode('utf-8'))
def encrypt(source,output,password):
    if len(password)<16: raise ValueError('口令至少需要 16 个字符')
    source=Path(source); output=Path(output)
    names=['password.key','recovery.json']+sorted(p.name for p in source.glob('recovery-*.json'))
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for name in names: z.writestr(name,(source/name).read_bytes())
    salt=secrets.token_bytes(16); nonce=secrets.token_bytes(12); header=MAGIC+salt+nonce
    encrypted=header+AESGCM(key(password,salt)).encrypt(nonce,data.getvalue(),header)
    with output.open('xb') as f:f.write(encrypted)
def decrypt(bundle,destination,password):
    data=Path(bundle).read_bytes(); header=data[:len(MAGIC)+28]
    if not header.startswith(MAGIC):raise ValueError('无效密钥包')
    salt=header[len(MAGIC):len(MAGIC)+16];nonce=header[-12:]
    plain=AESGCM(key(password,salt)).decrypt(nonce,data[len(header):],header)
    dest=Path(destination)
    if dest.exists():raise FileExistsError('目标目录已存在')
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or not {'password.key','recovery.json'}.issubset(names):raise ValueError('密钥包内容不完整')
        if any('/' in n or '\\' in n or not (n in {'password.key','recovery.json'} or n.startswith('recovery-') and n.endswith('.json')) for n in names):raise ValueError('密钥包路径无效')
        cloud.secure_directory(dest)
        for n in names:
            with (dest/n).open('xb') as f:f.write(z.read(n))
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['encrypt','decrypt']);p.add_argument('source');p.add_argument('destination');a=p.parse_args()
    password=getpass.getpass('请在本机输入恢复口令（不会显示）：')
    if a.action=='encrypt':
        if password!=getpass.getpass('再次输入恢复口令：'):raise ValueError('两次输入不一致')
        encrypt(a.source,a.destination,password)
    else:decrypt(a.source,a.destination,password)
    print('完成。请妥善保管恢复口令。')
if __name__=='__main__':main()

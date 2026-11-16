import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
 import recovery_bundle as bundle
 from cryptography.exceptions import InvalidTag
except ImportError:bundle=None

@unittest.skipUnless(bundle,'Install cryptography to test recovery bundle')
class BundleTests(unittest.TestCase):
 def test_roundtrip_and_wrong_password(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.mkdir()
   (source/'password.key').write_text('synthetic');(source/'recovery.json').write_text('{}')
   path=root/'bundle.enc';bundle.encrypt(source,path,'long synthetic passphrase')
   with self.assertRaises(InvalidTag):bundle.decrypt(path,root/'wrong','wrong synthetic passphrase')
   self.assertFalse((root/'wrong').exists())
   bundle.decrypt(path,root/'restore','long synthetic passphrase')
   self.assertEqual((root/'restore/password.key').read_text(),'synthetic')
   with self.assertRaises(FileExistsError):bundle.decrypt(path,root/'restore','long synthetic passphrase')

"""A failed demo download must not replace an existing scene."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import download_demo


class DemoDownloadTest(unittest.TestCase):
    def test_verified_replacement_and_failed_download_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'data/demo'
            folder.mkdir(parents=True)
            expected = b'verified scene'
            target = folder / 'scene.tif'
            target.write_bytes(b'existing scene')
            manifest = {'release': 'https://example.invalid/demo', 'files': [
                {'name': target.name, 'bytes': len(expected),
                 'sha256': hashlib.sha256(expected).hexdigest()}]}
            (folder / 'assets.json').write_text(json.dumps(manifest))
            with patch.object(download_demo, 'ROOT', root):
                with patch.object(download_demo, 'urlopen', return_value=io.BytesIO(b'broken')):
                    with self.assertRaisesRegex(ValueError, 'verification failed'):
                        download_demo.download(folder)
                self.assertEqual(target.read_bytes(), b'existing scene')
                self.assertFalse(list(folder.glob('*.part')))
                with patch.object(download_demo, 'urlopen', return_value=io.BytesIO(expected)):
                    download_demo.download(folder)
                self.assertEqual(target.read_bytes(), expected)
                with patch.object(download_demo, 'urlopen') as request:
                    download_demo.download(folder)
                    request.assert_not_called()


if __name__ == '__main__':
    unittest.main()

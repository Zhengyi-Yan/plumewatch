"""Download the verified Cyclone Gabrielle demo imagery (standard library only)."""
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def download(destination=ROOT / 'data/demo'):
    manifest = json.loads((ROOT / 'data/demo/assets.json').read_text())
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest['files']:
        target = destination / item['name']
        if target.is_file() and target.stat().st_size == item['bytes'] and digest(target) == item['sha256']:
            print(f'Already verified: {target.name}', flush=True)
            continue
        print(f'Downloading: {target.name}', flush=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination, suffix='.part', delete=False) as stream:
                temporary = Path(stream.name)
                with urlopen(manifest['release'] + '/' + item['name'], timeout=60) as response:
                    for block in iter(lambda: response.read(1024 * 1024), b''):
                        stream.write(block)
            if temporary.stat().st_size != item['bytes'] or digest(temporary) != item['sha256']:
                raise ValueError(f'Download verification failed: {target.name}')
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print('Demo ready. Restart the dashboard, open Time series, and load the Cyclone Gabrielle sequence.')


if __name__ == '__main__':
    try:
        download()
    except (OSError, ValueError) as error:
        raise SystemExit(f'Could not download the demo: {error}')

"""Download pinned pure-Python wheels and unpack into this release. Never runs pip."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def verify(path, digest):
    if not path.exists():
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == digest


def vendor(cache, offline=False, destination=None):
    cache = Path(cache).resolve()
    target = Path(destination or ROOT / 'vendor').resolve()
    cache.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    packages = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8-sig'))['packages']
    for package in packages:
        filename = package['filename']
        if Path(filename).name != filename or not filename.endswith('-none-any.whl'):
            raise ValueError('Only pinned pure-Python wheels are supported.')
        wheel = cache / filename
        if not verify(wheel, package['sha256']):
            if offline:
                raise ValueError(f'Missing or invalid cached archive: {filename}')
            print(f"Downloading {package['name']} {package['version']}…", flush=True)
            with urlopen(package['url'], timeout=60) as source, wheel.open('wb') as output:
                shutil.copyfileobj(source, output)
        if not verify(wheel, package['sha256']):
            raise ValueError(f'Archive checksum mismatch: {filename}')
        with ZipFile(wheel) as archive:
            for member in archive.infolist():
                path = (target / member.filename).resolve()
                if not path.is_relative_to(target):
                    raise ValueError('Invalid archive member path.')
                if '.data/' in member.filename:
                    raise ValueError('Wheel needs an installation scheme; add explicit support first.')
            archive.extractall(target)
    print(f'Local dependencies ready: {target}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=ROOT / '.downloads')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    vendor(args.cache, args.offline, args.target)

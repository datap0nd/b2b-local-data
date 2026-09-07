"""Download locked wheels and unpack app-local dependencies. Never runs pip."""
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
        if Path(filename).name != filename or not (filename.endswith('-none-any.whl') or filename.endswith('-cp313-cp313-win_amd64.whl')):
            raise ValueError('Only pure Python or locked CPython 3.13 Windows x64 wheels are supported.')
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
            for member in archive.infolist():
                parts=Path(member.filename).parts
                if parts and parts[0].endswith('.data'):
                    if len(parts)<3: continue
                    relative=Path(*parts[2:]) if parts[1] in ('purelib','platlib') else Path('_wheel_data',package['name'],*parts[1:])
                else:
                    relative=Path(member.filename)
                path=(target/relative).resolve()
                if not path.is_relative_to(target): raise ValueError('Invalid wheel installation path.')
                if member.is_dir():
                    path.mkdir(parents=True,exist_ok=True)
                else:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(member) as source,path.open('wb') as output:
                        shutil.copyfileobj(source,output)
    print(f'Local dependencies ready: {target}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=ROOT / '.downloads')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    vendor(args.cache, args.offline, args.target)

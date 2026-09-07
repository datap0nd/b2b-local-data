"""Unpack locked wheels locally; cache each package and reuse unchanged payloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from urllib.request import urlopen
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def verify(path,expected):
    return path.is_file() and digest(path)==expected


def contained(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or path==root:raise ValueError('Invalid archive or cache path.')
    return path


def cached_package(store,package):
    index=store/(package['sha256']+'.json')
    try:
        record=json.loads(index.read_text())
        directory=contained(store,record['directory'])
        if record['archive_sha256']!=package['sha256']:return None
        for name,expected in record['files'].items():
            if not verify(contained(directory,name),expected):return None
        return directory,record['files']
    except (OSError,ValueError,KeyError,TypeError):return None


def unpack_package(store,package,wheel):
    directory=store/(package['sha256']+'-'+uuid.uuid4().hex)
    directory.mkdir()
    files={}
    with ZipFile(wheel) as archive:
        for member in archive.infolist():
            # Validate both the archive path and the wheel's relocated .data path.
            contained(directory,member.filename)
            parts=Path(member.filename).parts
            if parts and parts[0].endswith('.data'):
                if len(parts)<3:continue
                relative=Path(*parts[2:]) if parts[1] in ('purelib','platlib') else Path('_wheel_data',package['name'],*parts[1:])
            else:relative=Path(member.filename)
            path=contained(directory,relative)
            if member.is_dir():
                path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(member) as source,path.open('wb') as output:shutil.copyfileobj(source,output)
                files[relative.as_posix()]=digest(path)
    record={'archive_sha256':package['sha256'],'directory':directory.name,'files':files}
    pending=store/(package['sha256']+'-'+uuid.uuid4().hex+'.json')
    pending.write_text(json.dumps(record),encoding='utf-8')
    os.replace(pending,store/(package['sha256']+'.json'))
    return directory,files


def vendor(cache,offline=False,destination=None,store=None,lock_path=None):
    cache=Path(cache).resolve()
    target=Path(destination or ROOT/'vendor').absolute()
    if target.is_symlink() or target.is_junction():raise ValueError('Vendor target must be a real directory.')
    target=target.resolve()
    store=Path(store or cache/'unpacked').resolve()
    cache.mkdir(parents=True,exist_ok=True);store.mkdir(parents=True,exist_ok=True)
    target.parent.mkdir(parents=True,exist_ok=True)
    packages=json.loads(Path(lock_path or ROOT/'dependencies.lock.json').read_text(encoding='utf-8-sig'))['packages']
    staging=target.parent/('vendor.staging.'+uuid.uuid4().hex);staging.mkdir()
    counts={'downloaded':0,'unpacked':0,'reused':0}
    for package in packages:
        filename=package['filename']
        if Path(filename).name!=filename or not (filename.endswith('-none-any.whl') or filename.endswith('-cp313-cp313-win_amd64.whl')):
            raise ValueError('Only pure Python or locked CPython 3.13 Windows x64 wheels are supported.')
        if len(package['sha256'])!=64 or any(c not in '0123456789abcdef' for c in package['sha256']):raise ValueError('Invalid archive digest.')
        cached=cached_package(store,package)
        if cached:
            counts['reused']+=1
        else:
            wheel=cache/filename
            if not verify(wheel,package['sha256']):
                if offline:raise ValueError('Missing or invalid cached archive: '+filename)
                print('Downloading '+package['name']+' '+package['version'],flush=True)
                with urlopen(package['url'],timeout=90) as source,wheel.open('wb') as output:shutil.copyfileobj(source,output)
                counts['downloaded']+=1
            if not verify(wheel,package['sha256']):raise ValueError('Archive checksum mismatch: '+filename)
            cached=unpack_package(store,package,wheel);counts['unpacked']+=1
        directory,files=cached
        for name,expected in files.items():
            source=contained(directory,name);path=contained(staging,name)
            if path.exists():
                if verify(path,expected):continue
                raise ValueError('Conflicting files in dependency wheels: '+name)
            path.parent.mkdir(parents=True,exist_ok=True)
            # Hard links reuse disk space on NTFS; copying is the portable fallback.
            try:os.link(source,path)
            except OSError:shutil.copyfile(source,path)
    if target.exists():
        backup=target.parent/('vendor.previous.'+uuid.uuid4().hex)
        # Verify both resolved targets before moving a complete directory on Windows.
        if target.resolve().parent!=target.parent or backup.resolve().parent!=target.parent:raise ValueError('Unsafe vendor replacement path.')
        target.rename(backup)
    if staging.resolve().parent!=target.parent or target.resolve().parent!=target.parent:raise ValueError('Unsafe vendor staging path.')
    staging.rename(target)
    print(f"Libraries: {counts['reused']} reused, {counts['unpacked']} unpacked, {counts['downloaded']} downloaded.",flush=True)
    return counts


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache',type=Path,default=ROOT/'.downloads')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--target',type=Path)
    parser.add_argument('--store',type=Path)
    args=parser.parse_args()
    vendor(args.cache,args.offline,args.target,args.store)

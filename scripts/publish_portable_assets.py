"""Maintainer command: mirror the locked upstream archives to GitHub, unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def gh(*args,check=True):
    result=subprocess.run(['gh',*args],capture_output=True,text=True)
    if check and result.returncode:
        raise RuntimeError('GitHub release operation failed: '+result.stderr)
    return result


def publish(repository,cache):
    cache.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'portable_assets.lock.json').read_text())
    for name,key in [('dependencies.lock.json','dependency_lock_sha256'),('runtime.lock.json','runtime_lock_sha256')]:
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=config[key]:
            raise RuntimeError('Refresh release metadata before publishing assets.')
    entries=[json.loads((ROOT/'runtime.lock.json').read_text())]+json.loads((ROOT/'dependencies.lock.json').read_text())['packages']
    files=[]
    for item in entries:
        path=cache/item['filename']
        valid=path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        if not valid:
            print('Fetching upstream archive: '+item['filename'],flush=True)
            with urlopen(item['url'],timeout=90) as source,path.open('wb') as output:shutil.copyfileobj(source,output)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Archive checksum mismatch: '+path.name)
        files.append(path)
    tag=config['release_tag']
    existing=gh('release','view',tag,'--repo',repository,'--json','assets,isDraft',check=False)
    if existing.returncode:
        notes=cache/'portable-release-notes.md'
        notes.write_text('Unmodified, SHA-256-verified Python runtime and library wheels for the portable Windows x64 application.\n\nVersions, upstream sources, and expected hashes are recorded in the repository locks. No pip or system installation is required.\n',encoding='utf-8')
        gh('release','create',tag,'--repo',repository,'--target','main','--draft','--title','Portable Python and dependencies','--notes-file',str(notes))
        info={'assets':[],'isDraft':True}
    else:info=json.loads(existing.stdout)
    present={asset['name']:asset for asset in info['assets']}
    for path,item in zip(files,entries):
        asset=present.get(path.name)
        if asset:
            if asset.get('digest')!='sha256:'+item['sha256']:
                raise RuntimeError('Existing GitHub asset has a missing or different digest: '+path.name)
            continue
        print('Publishing '+path.name,flush=True)
        gh('release','upload',tag,str(path),'--repo',repository)
    if info['isDraft']:gh('release','edit',tag,'--repo',repository,'--draft=false','--latest=false')
    print('Portable archives ready: '+tag)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository',default='datap0nd/b2b-local-data')
    parser.add_argument('--cache',type=Path,default=ROOT/'.downloads')
    args=parser.parse_args()
    publish(args.repository,args.cache.resolve())

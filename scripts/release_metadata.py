"""Generate release metadata without resolving or changing dependency versions."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')


def refresh(root=ROOT):
    packages=json.loads((root/'dependencies.lock.json').read_text())['packages']
    runtime=json.loads((root/'runtime.lock.json').read_text())
    identity='\n'.join(sorted(item['filename']+':'+item['sha256'] for item in [runtime]+packages))
    tag='portable-cp313-win_amd64-'+hashlib.sha256(identity.encode()).hexdigest()[:20]
    write_json(root/'portable_assets.lock.json',{'format':1,'release_tag':tag,
        'dependency_lock_sha256':digest(root/'dependencies.lock.json'),'runtime_lock_sha256':digest(root/'runtime.lock.json')})
    write_json(root/'release_manifest.json',{'app_version':(root/'VERSION').read_text().strip(),
        'query_plan_version':1,'data_schema_version':2,'python_tag':'cp313','platform':'win_amd64',
        'dependency_lock_sha256':digest(root/'dependencies.lock.json'),'runtime_lock_sha256':digest(root/'runtime.lock.json'),
        'portable_assets_lock_sha256':digest(root/'portable_assets.lock.json'),
        'dependencies':{item['name'].lower().replace('_','-'):item['version'] for item in packages}})
    return tag


if __name__=='__main__':
    print(refresh())

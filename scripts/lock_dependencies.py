"""Maintainer-only lock refresh for the declared versions; downloads metadata, never installs."""
import json
from pathlib import Path
import sys
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parent))
from release_metadata import refresh

ROOT=Path(__file__).resolve().parents[1]
VERSIONS={'pg8000':'1.31.5','scramp':'1.4.17','asn1crypto':'1.5.1','python-dateutil':'2.9.0.post0','six':'1.17.0',
          'pandas':'2.3.3','numpy':'2.3.5','pydantic':'2.12.5','pydantic-core':'2.41.5','SQLAlchemy':'2.0.44','greenlet':'3.2.4',
          'annotated-types':'0.7.0','typing-extensions':'4.15.0','typing-inspection':'0.4.2','pytz':'2025.2','tzdata':'2025.2',
          'fastapi':'0.116.2','starlette':'0.48.0','uvicorn':'0.35.0','anyio':'4.11.0','idna':'3.10','sniffio':'1.3.1',
          'h11':'0.16.0','click':'8.2.1','colorama':'0.4.6'}


if __name__=='__main__':
    packages=[]
    for name,version in VERSIONS.items():
        with urlopen(f'https://pypi.org/pypi/{name}/{version}/json',timeout=30) as response:
            metadata=json.load(response)
        wheels=[item for item in metadata['urls'] if item['filename'].endswith('-none-any.whl')]
        if not wheels:
            wheels=[item for item in metadata['urls'] if item['filename'].endswith('-cp313-cp313-win_amd64.whl')]
        if len(wheels)!=1: raise RuntimeError(f'Expected one compatible wheel for {name}')
        wheel=wheels[0]
        packages.append({'name':name,'version':version,'filename':wheel['filename'],'url':wheel['url'],'sha256':wheel['digests']['sha256']})
    lock=ROOT/'dependencies.lock.json'
    lock.write_text(json.dumps({'format':2,'platform':'win_amd64','python_tag':'cp313','packages':packages},indent=2)+'\n',encoding='utf-8',newline='\n')
    refresh()
    print(f'Locked {len(packages)} packages and the release ABI manifest.')

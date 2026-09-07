"""Inspect and roll back local release pointers without modifying data or processes."""
import argparse
import json
import os
from pathlib import Path
import uuid

from app_config import AppError


def checked_pointer(root,name):
    root=Path(root).resolve()
    try:
        pointer=json.loads((root/name).read_text(encoding='utf-8-sig'))
        release=Path(pointer['release']).resolve()
        python=Path(pointer['python']).resolve()
        if not release.is_relative_to(root/'releases') or not python.is_relative_to(root/'runtime'):
            raise ValueError
        if not (release/'run.py').is_file() or not python.is_file(): raise ValueError
        return pointer
    except (OSError,ValueError,KeyError,TypeError):
        raise AppError('Release pointer is invalid or refers outside this installation.') from None


def rollback(root):
    root=Path(root).resolve()
    pointer=checked_pointer(root,'previous.json')
    temporary=root/f'rollback-{uuid.uuid4().hex}.json'
    temporary.write_text(json.dumps(pointer,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,root/'current.json')
    return pointer


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    result=rollback(args.home) if args.rollback else checked_pointer(args.home,'current.json')
    print('Selected commit:',result['commit'])
    if args.rollback: print('Stop the current app and run start.ps1 to use the selected release. Local data is unchanged.')

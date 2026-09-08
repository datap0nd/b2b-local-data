"""Launch from portable Python; verify the release before importing native packages."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'vendor'))


def main():
    from app_config import AppError, Settings, verify_release
    parser=argparse.ArgumentParser(description='B2B Salesforce Query Agent')
    parser.add_argument('--home',type=Path,default=ROOT)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--host',help='Explicit listen address for the Windows service.')
    parser.add_argument('--port',type=int,help='Explicit listen port for the Windows service.')
    args=parser.parse_args()
    try:
        verify_release()
        if args.self_test:
            import unittest
            suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            raise SystemExit(0 if result.wasSuccessful() else 1)
        settings=Settings.load(args.home)
        if args.check:
            print('Release ABI, dependencies, and local configuration are valid. Live SQL/Qwen have not been tested.')
            return
        import uvicorn
        from ui_app import create_app
        app=create_app(settings)
        port=args.port if args.port is not None else settings.number('APP_PORT',8765,high=65535)
        if not 1 <= port <= 65535:
            raise AppError('--port must be between 1 and 65535.')
        host=(args.host or settings.listen_host).strip()
        print(f'B2B Salesforce Query Agent: http://{"127.0.0.1" if host in ("0.0.0.0","::") else host}:{port} (database: {settings.get("DB_KIND","demo")}, listening on {host})',flush=True)
        uvicorn.run(app,host=host,port=port,access_log=False,log_level='critical',proxy_headers=False)
    except AppError as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__': main()

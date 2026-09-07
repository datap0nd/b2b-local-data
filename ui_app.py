"""Persistent FastAPI process; ordinary browser interactions do not rerun Python."""
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
from time import monotonic
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from acceptance_runner import AcceptanceRunner
from acceptance_suite import manifest
from app_config import APP_VERSION, ROOT, AppError, verify_release
from data_layer import DataRepository
from history_store import HistoryStore
from query_engine import PlannerClient, QueryExecutor, parse_plan
from query_service import QueryService


class AskRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question: str=Field(min_length=1,max_length=4000)
    session_id: str | None=Field(default=None,max_length=64)
    view: Literal['auto','summary','detail']='auto'


class LoginRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)


class TitleRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str=Field(min_length=1,max_length=100)


class SessionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id: str=Field(min_length=1,max_length=64)


class SampleRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id: str | None=Field(default=None,max_length=64)
    view: Literal['summary','detail']='summary'
    intent: Literal['table','metric','chart']='table'


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    only_failed_from: str | None=Field(default=None,min_length=32,max_length=32,pattern='^[0-9a-f]{32}$')


class StepRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    step: int=Field(ge=0,le=999)


class BrowserObservation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    check: int=Field(ge=1,le=99)
    status: Literal['pass','fail','blocked']
    expected: dict | list | str | None=None
    observed: dict | list | str | None=None
    notes: str | None=Field(default=None,max_length=2000)


class Snapshots:
    def __init__(self,repository,seconds=60):
        self.repository,self.seconds=repository,seconds
        self.current=None
        self.loaded=0
        self.loaded_at=None
        self.lock=threading.Lock()

    def get(self,force=False):
        with self.lock:
            if force or self.current is None or monotonic()-self.loaded>=self.seconds:
                try: current=self.repository.load()
                except Exception:
                    self.current=None
                    self.loaded=0
                    raise
                self.current=current
                self.loaded=monotonic()
                self.loaded_at=datetime.now(timezone.utc).isoformat()
            return self.current,self.loaded_at


COOKIE='b2b_user'
NAME_PATTERN=re.compile(r"^[^\x00-\x1f\x7f]{1,60}$")


def trusted_proxies(settings):
    return {host.strip() for host in settings.get('B2B_TRUSTED_PROXIES').split(',') if host.strip()}


def client_ip(settings,request):
    """The caller's address; X-Forwarded-For counts only when a trusted proxy sent it."""
    peer=request.client.host if request.client else ''
    forwarded=request.headers.get('x-forwarded-for','')
    if forwarded and peer in trusted_proxies(settings):
        return forwarded.split(',')[0].strip()[:64]
    return peer


def cookie_secret(settings):
    path=settings.data_dir/'.cookie_secret'
    try: value=path.read_text(encoding='utf-8').strip()
    except OSError: value=''
    if len(value)<32:
        value=secrets.token_hex(32)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(value,encoding='utf-8')
    return value.encode()


def sign_name(secret,name):
    encoded=base64.urlsafe_b64encode(name.encode()).decode().rstrip('=')
    return encoded+'.'+hmac.new(secret,encoded.encode(),hashlib.sha256).hexdigest()


def read_signed_name(secret,value):
    if not value or '.' not in value: return None
    encoded,signature=value.rsplit('.',1)
    if not hmac.compare_digest(hmac.new(secret,encoded.encode(),hashlib.sha256).hexdigest(),signature): return None
    try: name=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)).decode()
    except (ValueError,UnicodeDecodeError): return None
    return name if NAME_PATTERN.match(name) else None


def clean_name(name):
    name=' '.join((name or '').split())
    if not NAME_PATTERN.match(name): raise AppError('Enter your name (up to 60 characters).')
    return name


def request_owner(settings,request,secret):
    """Identity for history scoping: a trusted proxy header, the signed name cookie, or the local Windows user."""
    peer=request.client.host if request.client else ''
    forwarded=request.headers.get(settings.get('B2B_AUTH_USER_HEADER','X-Forwarded-User'))
    if forwarded and peer in trusted_proxies(settings):
        expected=settings.get('B2B_PROXY_SHARED_SECRET')
        if len(expected)<32 or not secrets.compare_digest(request.headers.get('X-B2B-Proxy-Secret',''),expected):
            raise AppError('The trusted authentication proxy did not provide its shared secret.')
        if not forwarded.strip() or len(forwarded)>200: raise AppError('Invalid authenticated user identity.')
        return 'proxy:'+forwarded.strip()
    if settings.get('B2B_IDENTITY','name')=='name':
        name=read_signed_name(secret,request.cookies.get(COOKIE))
        if name: return 'name:'+name
        return None
    try: local=ipaddress.ip_address(peer).is_loopback
    except ValueError: local=False
    if local and settings.flag('B2B_ALLOW_LOCALHOST_IDENTITY',True): return 'local:'+getpass.getuser()
    raise AppError('An authenticated user identity is required.')


def create_app(settings,repository=None,planner=None,store=None,enforce_release=True):
    if enforce_release: verify_release()
    app=FastAPI(title='B2B Salesforce Query Agent',version=APP_VERSION,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store or HistoryStore(settings.data_dir/'history.sqlite3')
    app.state.planner=planner or PlannerClient(settings)
    app.state.snapshots=Snapshots(repository or DataRepository(settings),settings.number('B2B_CACHE_SECONDS',60,low=0,high=3600))
    app.state.executor=QueryExecutor()
    app.state.service=QueryService(app.state.planner,app.state.executor)
    app.state.acceptance=AcceptanceRunner(settings,app.state.snapshots.repository,app.state.service,settings.data_dir)
    lane=app.state.service.lane
    secret=cookie_secret(settings)
    public_paths={'/','/app.js','/style.css','/test.js','/favicon.ico','/api/login','/api/me','/api/status'}

    @app.middleware('http')
    async def local_boundary(request:Request,call_next):
        port=settings.number('APP_PORT',8765,high=65535)
        origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
        public=settings.get('B2B_PUBLIC_ORIGIN').rstrip('/')
        if public: origins.add(public)
        hosts={origin.split('://',1)[1] for origin in origins}
        host=request.headers.get('host','')
        origin=request.headers.get('origin')
        # When serving colleagues on the network, any host name on the app port is fine as long as requests stay same-origin.
        lan=settings.listen_host not in ('127.0.0.1','localhost','::1') and host.rsplit(':',1)[-1]==str(port)
        same_origin=origin is None or origin in origins or origin.split('://',1)[-1]==host
        if not ((host in hosts or lan) and same_origin):
            return JSONResponse({'error':'Use the configured application address.'},status_code=403)
        if request.method=='POST':
            try: size=int(request.headers.get('content-length','0'))
            except ValueError: size=-1
            if size<0 or size>32000 or request.headers.get('content-type','').split(';')[0]!='application/json' or 'transfer-encoding' in request.headers:
                return JSONResponse({'error':'A bounded JSON request is required.'},status_code=400)
        try: request.state.owner=request_owner(settings,request,secret)
        except AppError as error: return JSONResponse({'error':str(error)},status_code=401)
        request.state.ip=client_ip(settings,request)
        if request.state.owner is None and request.url.path not in public_paths:
            return JSONResponse({'error':'Enter your name to continue.','login_required':True},status_code=401)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(AppError)
    async def app_error(request,error): return JSONResponse({'error':str(error)},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error): return JSONResponse({'error':'Invalid request. Check the question, session, and table layout.'},status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request,error): return JSONResponse({'error':'The request failed. Check the local configuration and source schema.'},status_code=500)

    @app.get('/')
    def index(): return FileResponse(ROOT/'web/index.html',media_type='text/html')

    @app.get('/app.js')
    def javascript(): return FileResponse(ROOT/'web/app.js',media_type='text/javascript')

    @app.get('/style.css')
    def stylesheet(): return FileResponse(ROOT/'web/style.css',media_type='text/css')

    @app.get('/test.js')
    def test_script(): return FileResponse(ROOT/'web/test.js',media_type='text/javascript')

    @app.get('/favicon.ico')
    def favicon(): return Response(status_code=204)

    def display_name(owner):
        return owner.split(':',1)[1] if owner and ':' in owner else (owner or '')

    @app.post('/api/login')
    def login(request:Request,payload:LoginRequest):
        name=clean_name(payload.name)
        app.state.store.log_login(name,request.state.ip,request.headers.get('user-agent',''))
        response=JSONResponse({'name':name,'owner':'name:'+name})
        response.set_cookie(COOKIE,sign_name(secret,name),max_age=365*24*3600,httponly=True,samesite='lax',path='/')
        return response

    @app.post('/api/logout')
    def logout(request:Request):
        response=JSONResponse({'ok':True})
        response.delete_cookie(COOKIE,path='/')
        return response

    @app.get('/api/me')
    def me(request:Request):
        owner=request.state.owner
        return {'login_required':owner is None,'name':display_name(owner),'owner':owner,'ip':request.state.ip,'identity':settings.get('B2B_IDENTITY','name')}

    @app.get('/api/access-log')
    def access_log(request:Request): return app.state.store.access_log()

    @app.get('/api/status')
    def status(request:Request):
        kind=settings.get('DB_KIND','demo')
        return {'version':APP_VERSION,'database':kind,'source':settings.source_label,'previews':kind in ('demo','csv'),'name':display_name(request.state.owner),
                'model':settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or 'Not configured',
                'model_source':settings.source_of('LLM_MODEL_NAME') if hasattr(settings,'source_of') else 'default','endpoint_source':settings.source_of('LLM_API_URL') if hasattr(settings,'source_of') else 'default',
                'cache_seconds':app.state.snapshots.seconds,'snapshot_at':app.state.snapshots.loaded_at,
                'qualification':app.state.acceptance.qualification(request.state.owner) if request.state.owner else None}

    @app.get('/api/sessions')
    def sessions(request:Request): return {'sessions':app.state.store.list(request.state.owner)}

    @app.post('/api/sessions')
    def new_session(request:Request): return {'session_id':app.state.store.create(request.state.owner)}

    @app.get('/api/sessions/{session_id}')
    def session(request:Request,session_id:str): return app.state.store.read(request.state.owner,session_id)

    @app.delete('/api/sessions/{session_id}')
    def delete_session(request:Request,session_id:str):
        app.state.store.delete(request.state.owner,session_id)
        app.state.store.log_activity(request.state.owner,request.state.ip,'delete',session_id)
        return {'ok':True}

    @app.post('/api/sessions/{session_id}/title')
    def rename_session(request:Request,session_id:str,payload:TitleRequest):
        app.state.store.rename(request.state.owner,session_id,payload.title);return {'ok':True}

    @app.post('/api/sessions/{session_id}/turns/{turn_id}/run')
    def run_turn(request:Request,session_id:str,turn_id:int):
        plan=app.state.store.turn_plan(request.state.owner,session_id,turn_id)
        app.state.store.log_activity(request.state.owner,request.state.ip,'show',session_id,f'turn {turn_id}')
        return {'kind':'table','table':execute(plan),'plan':plan.model_dump(mode='json'),'session_id':session_id,'suggestions':[]}

    def execute(plan):
        views,timestamp=app.state.snapshots.get()
        result=app.state.executor.execute(views,plan)
        result['snapshot_at']=timestamp
        return result

    def complete(owner,session_id,question,plan):
        table=execute(plan)
        app.state.store.append(owner,session_id,question,f"{table['total_rows']} result rows at {plan.grain.value} grain.",plan)
        return {'kind':'table','table':table,'plan':plan.model_dump(mode='json'),'suggestions':plan.suggestions,'session_id':session_id}

    @app.post('/api/ask')
    def ask(request:Request,payload:AskRequest):
        if not lane.acquire(blocking=False): return JSONResponse({'error':'A question is running. Try again when it finishes.'},status_code=429)
        try:
            if not payload.question.strip(): raise AppError('Enter a question.')
            owner=request.state.owner
            session_id=payload.session_id or app.state.store.create(owner)
            app.state.store.log_activity(owner,request.state.ip,'ask',session_id,payload.question.strip())
            views,timestamp=app.state.snapshots.get()
            return app.state.service.ask(app.state.store,owner,session_id,payload.question,payload.view,views,timestamp)
        finally: lane.release()

    @app.post('/api/sample')
    def sample(request:Request,payload:SampleRequest):
        # Previews build a fixed plan locally; they never call the model. Demo and CSV sources support them.
        if settings.get('DB_KIND','demo') not in ('demo','csv'): raise AppError('Previews without Qwen are available for fictional data and local CSV files.')
        if not lane.acquire(blocking=False): return JSONResponse({'error':'A question is already running.'},status_code=429)
        try:
            owner=request.state.owner
            session_id=payload.session_id or app.state.store.create(owner)
            app.state.store.log_activity(owner,request.state.ip,'preview',session_id,f'{payload.intent} {payload.view}')
            values={'grain':'opportunity' if payload.view=='summary' else 'opportunity_sku','intent':payload.intent}
            if payload.intent!='table': values.update(dimensions=['stage_group'],measures=['amount','opportunity_count'])
            if payload.intent=='chart': values['chart_type']='bar'
            return complete(owner,session_id,f"Preview: {payload.view} {'table' if payload.intent=='table' else payload.intent}",parse_plan(values))
        finally: lane.release()

    @app.post('/api/rerun')
    def rerun(request:Request,payload:SessionRequest):
        _,plan=app.state.store.context(request.state.owner,payload.session_id)
        if plan is None: raise AppError('This conversation has no completed query yet.')
        app.state.store.log_activity(request.state.owner,request.state.ip,'rerun',payload.session_id)
        return {'kind':'table','table':execute(plan),'plan':plan.model_dump(mode='json'),'session_id':payload.session_id,'suggestions':[]}

    # Acceptance-test APIs: the server owns the suite, the order, and the expected results.
    @app.get('/api/test/suite')
    def test_suite(request:Request): return manifest()|{'qualification':app.state.acceptance.qualification(request.state.owner)}

    @app.get('/api/test/runs')
    def test_runs(request:Request):
        runs=app.state.acceptance.list_runs(request.state.owner)
        return {'runs':[{'id':r['id'],'status':r['status'],'started_at':r['started_at'],'finished_at':r.get('finished_at'),'scope':r['scope'],'full_pass':app.state.acceptance.is_full_pass(r),
                         'source_fingerprint':r['identity']['source_fingerprint']} for r in runs],'qualification':app.state.acceptance.qualification(request.state.owner)}

    @app.post('/api/test/runs')
    def test_start(request:Request,payload:RunRequest):
        app.state.store.log_activity(request.state.owner,request.state.ip,'test',None,'acceptance run started')
        return app.state.acceptance.start(request.state.owner,payload.only_failed_from)

    @app.get('/api/test/runs/{run_id}')
    def test_run(request:Request,run_id:str):
        status=app.state.acceptance.status(request.state.owner,run_id)
        status['comparison']=app.state.acceptance.comparison(request.state.owner,app.state.acceptance._load(request.state.owner,run_id))
        return status

    @app.get('/api/test/runs/{run_id}/steps/{step_id}')
    def test_step_detail(request:Request,run_id:str,step_id:str):
        detail=app.state.acceptance.detail(request.state.owner,run_id,step_id)
        if detail is None: raise AppError('Unknown step.')
        return detail

    @app.post('/api/test/runs/{run_id}/step')
    def test_step(request:Request,run_id:str,payload:StepRequest): return app.state.acceptance.step(request.state.owner,run_id,payload.step)

    @app.post('/api/test/runs/{run_id}/browser')
    def test_browser(request:Request,run_id:str,payload:BrowserObservation):
        return app.state.acceptance.record_browser(request.state.owner,run_id,payload.check,payload.status,payload.expected,payload.observed,payload.notes)

    @app.post('/api/test/runs/{run_id}/cancel')
    def test_cancel(request:Request,run_id:str): return app.state.acceptance.cancel(request.state.owner,run_id)

    @app.get('/api/test/runs/{run_id}/report')
    def test_report(request:Request,run_id:str):
        report=app.state.acceptance.report(request.state.owner,run_id)
        run=app.state.acceptance._load(request.state.owner,run_id)
        stamp=run['started_at'].replace(':','').replace('-','')[:15]
        return Response(report,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="b2b-test-{stamp}-{run_id[:8]}.md"'})

    @app.post('/api/refresh')
    def refresh():
        views,timestamp=app.state.snapshots.get(force=True)
        return {'snapshot_at':timestamp,'source':views.source,'source_name':views.source_name,'opportunities':len(views.opportunity),'skus':len(views.sku)}

    return app

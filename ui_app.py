"""Persistent FastAPI process; ordinary browser interactions do not rerun Python.

The compiled frontend (web/dist, built from frontend/ and committed with its source fingerprint) is served as static
assets. The browser talks to a small API: a public bootstrap (identity state and UI capabilities only), conversations
with saved answers, questions, deterministic result actions keyed by owned conversation/turn, and, when
B2B_ENABLE_ACCEPTANCE_UI is on, the development acceptance-test routes."""
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

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from acceptance_runner import AcceptanceRunner
from acceptance_suite import manifest
from answer_text import compose_answer, default_suggestions
from app_config import APP_VERSION, ROOT, AppError, verify_release
from data_layer import DataRepository
from history_store import HistoryStore, ordered_supporting_rows, supporting_csv
from query_engine import CALCULATION_VERSION, PlannerClient, QueryExecutor, parse_plan
from query_service import QueryService, public_answer_payload

DIST = ROOT / 'web/dist'
ASSET_TYPES = {'.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.png': 'image/png', '.map': 'application/json', '.json': 'application/json', '.ico': 'image/x-icon'}


class AskRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question: str=Field(min_length=1,max_length=4000)
    session_id: str | None=Field(default=None,max_length=64)
    # Question submission always uses automatic interpretation; the value is kept for the acceptance runner and older callers.
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


class ActionRequest(BaseModel):
    """A supported result action: the browser names the action and its option, never a plan or SQL."""
    model_config=ConfigDict(extra='forbid')
    action: Literal['view','presentation']
    view: Literal['summary','detail'] | None=None
    presentation: Literal['table','chart','cards'] | None=None


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    only_failed_from: str | None=Field(default=None,min_length=32,max_length=32,pattern='^[0-9a-f]{32}$')
    # Replay a retained snapshot of an earlier run for diagnosis; replay runs never qualify for delivery.
    replay_from: str | None=Field(default=None,min_length=32,max_length=32,pattern='^[0-9a-f]{32}$')


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
    """The server-managed current dataset; a verified update time is reused only for the same dataset fingerprint."""
    def __init__(self,repository,seconds=60):
        self.repository,self.seconds=repository,seconds
        self.current=None
        self.loaded=0
        self.loaded_at=None
        self.verified={}
        self.lock=threading.Lock()

    def get(self,force=False):
        with self.lock:
            if force or self.current is None or monotonic()-self.loaded>=self.seconds:
                try: current=self.repository.load()
                except Exception:
                    self.current=None
                    self.loaded=0
                    raise
                fingerprint=getattr(current,'fingerprint',None)
                freshness=getattr(current,'freshness',None) or {}
                if freshness.get('status')=='verified' and fingerprint:
                    self.verified[fingerprint]=dict(freshness)
                elif fingerprint in self.verified:
                    current.freshness=dict(self.verified[fingerprint])|{'reused':True}
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
    acceptance_ui=settings.flag('B2B_ENABLE_ACCEPTANCE_UI',True)
    app.state.acceptance=AcceptanceRunner(settings,app.state.snapshots.repository,app.state.service,settings.data_dir) if acceptance_ui else None
    lane=app.state.service.lane
    secret=cookie_secret(settings)
    public_paths={'/','/favicon.ico','/api/login','/api/me','/api/status','/api/bootstrap'}

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
        path=request.url.path
        if request.state.owner is None and path not in public_paths and not path.startswith('/assets/'):
            return JSONResponse({'error':'Enter your name to continue.','login_required':True},status_code=401)
        response=await call_next(request)
        response.headers['Cache-Control']='public, max-age=31536000, immutable' if path.startswith('/assets/') else 'no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(AppError)
    async def app_error(request,error): return JSONResponse({'error':str(error)},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error): return JSONResponse({'error':'Invalid request. Check the question, session, and requested action.'},status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request,error): return JSONResponse({'error':'The request failed. Check the local configuration and source schema.'},status_code=500)

    # ----- compiled frontend -----
    @app.get('/')
    def index():
        page=DIST/'index.html'
        if not page.exists(): raise AppError('The compiled frontend is missing (web/dist). Run the frontend build or reinstall the release.')
        return FileResponse(page,media_type='text/html')

    @app.get('/assets/{name:path}')
    def asset(name:str):
        if not re.fullmatch(r'[A-Za-z0-9._-]+',name): return Response(status_code=404)
        path=DIST/'assets'/name
        if not path.is_file(): return Response(status_code=404)
        return FileResponse(path,media_type=ASSET_TYPES.get(path.suffix,'application/octet-stream'))

    @app.get('/favicon.ico')
    def favicon(): return Response(status_code=204)

    def display_name(owner):
        return owner.split(':',1)[1] if owner and ':' in owner else (owner or '')

    # ----- identity -----
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

    @app.get('/api/bootstrap')
    def bootstrap(request:Request):
        """What the browser needs to start: identity state and UI capabilities. No model, version, or source details."""
        owner=request.state.owner
        kind=settings.get('DB_KIND','demo')
        return {'identity':{'login_required':owner is None,'name':display_name(owner),'mode':settings.get('B2B_IDENTITY','name')},
                'capabilities':{'acceptance_ui':acceptance_ui,'samples':kind in ('demo','csv'),'saved_results':True,'contract_version':2,'views':['summary','detail'],'presentations':['table','chart','cards']}}

    @app.get('/api/access-log')
    def access_log(request:Request): return app.state.store.access_log()

    @app.get('/api/status')
    def status(request:Request):
        kind=settings.get('DB_KIND','demo')
        return {'version':APP_VERSION,'database':kind,'source':settings.source_label,'previews':kind in ('demo','csv'),'name':display_name(request.state.owner),
                'stream':settings.flag('B2B_LLM_STREAM',True) if settings.get('AI_PROVIDER','openai_compatible')=='openai_compatible' else False,
                'model':settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or 'Not configured',
                'model_source':settings.source_of('LLM_MODEL_NAME') if hasattr(settings,'source_of') else 'default','endpoint_source':settings.source_of('LLM_API_URL') if hasattr(settings,'source_of') else 'default',
                'cache_seconds':app.state.snapshots.seconds,'snapshot_at':app.state.snapshots.loaded_at,'acceptance_ui':acceptance_ui,
                'qualification':app.state.acceptance.qualification(request.state.owner) if app.state.acceptance and request.state.owner else None}

    @app.get('/api/freshness')
    def freshness(request:Request):
        """Verified time of the current cached dataset, never an answer or app-load time."""
        views,_=app.state.snapshots.get()
        return {'freshness':getattr(views,'freshness',None) or {'status':'unavailable','updated_at':None,'reason':'No verified data-update time is available for this source.'}}

    # ----- conversations and saved answers -----
    @app.get('/api/sessions')
    def sessions(request:Request,q:str|None=None): return {'sessions':app.state.store.list(request.state.owner,(q or '')[:100] or None)}

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

    @app.get('/api/sessions/{session_id}/turns/{turn_id}/result')
    def saved_result(request:Request,session_id:str,turn_id:int):
        """The original answer as saved with the turn: restored without SQL or model calls."""
        saved=app.state.store.load_result(request.state.owner,session_id,turn_id)
        if saved is None:
            turn=app.state.store.turn(request.state.owner,session_id,turn_id)
            return {'available':False,'turn_id':turn_id,'kind':turn['kind'],'can_rerun':bool(turn['plan']),'message':'This answer predates saved results. Run with current data to get a new, dated answer.'}
        if (saved.get('table',{}).get('metadata') or {}).get('calculation_version')!=CALCULATION_VERSION:
            return {'available':False,'turn_id':turn_id,'kind':'data','can_rerun':True,'message':'This answer used earlier amount and summary calculations. Run with current data for a corrected answer. The original record is preserved.'}
        return public_answer_payload({'available':True,'turn_id':turn_id,'session_id':session_id,'suggestions':default_suggestions(saved['table'])}|saved)

    @app.get('/api/sessions/{session_id}/turns/{turn_id}/supporting')
    def supporting_page(request:Request,session_id:str,turn_id:int,view:Literal['summary','detail']='summary',
                        page:int=Query(default=0,ge=0),page_size:int=Query(default=50,ge=1,le=200),sort:str|None=None,
                        direction:Literal['asc','desc']='asc'):
        """Page frozen evidence from the saved answer, without a current-data read."""
        result=app.state.store.load_supporting(request.state.owner,session_id,turn_id,view)
        if not result['available']:
            return result
        table=result['table']
        ordered=ordered_supporting_rows(table,sort,direction)
        start=page*page_size
        page_rows=ordered[start:start+page_size]
        visible=dict(table,rows=page_rows,truncated=len(page_rows)<len(ordered))
        return {'available':True,'view':view,'page':page,'page_size':page_size,'total_rows':len(ordered),'table':visible}

    @app.get('/api/sessions/{session_id}/turns/{turn_id}/supporting.csv')
    def supporting_download(request:Request,session_id:str,turn_id:int,view:Literal['summary','detail']='summary',
                            sort:str|None=None,direction:Literal['asc','desc']='asc'):
        """Export every frozen matching business row in the selected exact order."""
        result=app.state.store.load_supporting(request.state.owner,session_id,turn_id,view)
        if not result['available']:
            raise AppError(result.get('message') or 'The complete supporting list is unavailable.')
        table=result['table']
        body=supporting_csv(table,ordered_supporting_rows(table,sort,direction)).encode('utf-8')
        return Response(body,media_type='text/csv; charset=utf-8',headers={
            'Content-Disposition':f'attachment; filename="b2b-supporting-{view}.csv"','Cache-Control':'private, no-store'})

    @app.post('/api/sessions/{session_id}/turns/{turn_id}/actions')
    def result_action(request:Request,session_id:str,turn_id:int,payload:ActionRequest):
        """Deterministic view changes on a saved answer: Summary/Detailed or table/chart/cards presentation. No SQL, no model."""
        saved=app.state.store.load_result(request.state.owner,session_id,turn_id)
        if saved is None: raise AppError('This answer has no saved result to switch. Run with current data first.')
        if (saved.get('table',{}).get('metadata') or {}).get('calculation_version')!=CALCULATION_VERSION:
            raise AppError('This answer used earlier calculations. Run with current data before exploring its results.')
        table=saved['table']
        if payload.action=='view':
            if payload.view is None: raise AppError('Choose summary or detail.')
            if payload.view==table.get('view'): chosen=table
            else:
                chosen=(saved.get('variants') or {}).get(payload.view)
                if not chosen or 'rows' not in chosen: raise AppError((chosen or {}).get('error') or 'That view was not saved with this answer.')
            app.state.store.log_activity(request.state.owner,request.state.ip,'view',session_id,f'turn {turn_id} {payload.view}')
            return {'turn_id':turn_id,'table':chosen,'answer':compose_answer(chosen),'variants_available':sorted(k for k,v in (saved.get('variants') or {}).items() if 'rows' in v)}
        if payload.presentation is None: raise AppError('Choose table, chart, or cards.')
        if table.get('result_kind')!='aggregate': raise AppError('Chart and Data switching applies to grouped answers.')
        if payload.presentation=='chart' and not table.get('chart'): raise AppError('This answer has no chart specification.')
        return {'turn_id':turn_id,'table':dict(table,presentation=payload.presentation),'answer':saved.get('answer') or compose_answer(table)}

    @app.post('/api/sessions/{session_id}/turns/{turn_id}/run')
    def run_turn(request:Request,session_id:str,turn_id:int):
        """Run with current data: a new dated answer from the saved plan; the original turn is never overwritten."""
        turn=app.state.store.turn(request.state.owner,session_id,turn_id)
        plan=app.state.store.turn_plan(request.state.owner,session_id,turn_id)
        app.state.store.log_activity(request.state.owner,request.state.ip,'rerun',session_id,f'turn {turn_id}')
        views,timestamp=app.state.snapshots.get()
        payload=app.state.service.execute_and_save(app.state.store,request.state.owner,session_id,turn['question'],plan,views,timestamp,rerun_of=turn_id)
        return public_answer_payload({'kind':'table','suggestions':[]}|payload)

    # ----- questions -----
    @app.post('/api/ask')
    def ask(request:Request,payload:AskRequest):
        if not lane.acquire(blocking=False): return JSONResponse({'error':'A question is running. Try again when it finishes.'},status_code=429)
        try:
            if not payload.question.strip(): raise AppError('Enter a question.')
            owner=request.state.owner
            session_id=payload.session_id or app.state.store.create(owner)
            app.state.store.log_activity(owner,request.state.ip,'ask',session_id,payload.question.strip())
            views,timestamp=app.state.snapshots.get()
            return public_answer_payload(app.state.service.ask(app.state.store,owner,session_id,payload.question,payload.view,views,timestamp))
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
            grain='opportunity' if payload.view=='summary' else 'opportunity_sku'
            if payload.intent=='table': values={'result_kind':'rows','presentation':'table','grain':grain}
            else: values={'result_kind':'aggregate','presentation':'chart' if payload.intent=='chart' else 'table','grain':grain,'group_by':['stage_group'],'measures':['amount','opportunity_count'],'chart_type':'bar' if payload.intent=='chart' else None}
            views,timestamp=app.state.snapshots.get()
            question=f"Preview: {payload.view} {'table' if payload.intent=='table' else payload.intent}"
            return public_answer_payload({'kind':'table','suggestions':[]}|app.state.service.execute_and_save(app.state.store,owner,session_id,question,parse_plan(values),views,timestamp))
        finally: lane.release()

    @app.post('/api/rerun')
    def rerun(request:Request,payload:SessionRequest):
        """Run the conversation's active plan against the current snapshot as a new dated answer."""
        _,plan=app.state.store.context(request.state.owner,payload.session_id)
        if plan is None: raise AppError('This conversation has no completed query yet.')
        app.state.store.log_activity(request.state.owner,request.state.ip,'rerun',payload.session_id)
        views,timestamp=app.state.snapshots.get()
        saved=app.state.store.read(request.state.owner,payload.session_id)
        question=next((t['question'] for t in reversed(saved['turns']) if t.get('plan')),'Run with current data')
        return public_answer_payload({'kind':'table','suggestions':[]}|app.state.service.execute_and_save(app.state.store,request.state.owner,payload.session_id,question,plan,views,timestamp))

    if acceptance_ui:
        # Acceptance-test APIs (development only): the server owns the suite, the order, and the expected results.
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
            return app.state.acceptance.start(request.state.owner,payload.only_failed_from,replay_from=payload.replay_from)

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
        def test_step(request:Request,run_id:str,payload:StepRequest):
            result=app.state.acceptance.step(request.state.owner,run_id,payload.step)
            if result.get('table'): result['answer']=compose_answer(result['table'])   # the same deterministic text the app shows
            return result

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

    return app

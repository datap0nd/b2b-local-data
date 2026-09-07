"""Persistent FastAPI process; ordinary browser interactions do not rerun Python."""
from datetime import datetime, timezone
import getpass
import ipaddress
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


def request_owner(settings,request):
    peer=request.client.host if request.client else ''
    trusted={host.strip() for host in settings.get('B2B_TRUSTED_PROXIES').split(',') if host.strip()}
    forwarded=request.headers.get(settings.get('B2B_AUTH_USER_HEADER','X-Forwarded-User'))
    if forwarded and peer in trusted:
        expected=settings.get('B2B_PROXY_SHARED_SECRET')
        if len(expected)<32 or not secrets.compare_digest(request.headers.get('X-B2B-Proxy-Secret',''),expected):
            raise AppError('The trusted authentication proxy did not provide its shared secret.')
        if not forwarded.strip() or len(forwarded)>200: raise AppError('Invalid authenticated user identity.')
        return 'proxy:'+forwarded.strip()
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

    @app.middleware('http')
    async def local_boundary(request:Request,call_next):
        port=settings.number('APP_PORT',8765,high=65535)
        origins={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
        public=settings.get('B2B_PUBLIC_ORIGIN').rstrip('/')
        if public: origins.add(public)
        hosts={origin.split('://',1)[1] for origin in origins}
        if request.headers.get('host') not in hosts or request.headers.get('origin',next(iter(origins))) not in origins:
            return JSONResponse({'error':'Use the configured application address.'},status_code=403)
        if request.method=='POST':
            try: size=int(request.headers.get('content-length','0'))
            except ValueError: size=-1
            if size<0 or size>32000 or request.headers.get('content-type','').split(';')[0]!='application/json' or 'transfer-encoding' in request.headers:
                return JSONResponse({'error':'A bounded JSON request is required.'},status_code=400)
        try: request.state.owner=request_owner(settings,request)
        except AppError as error: return JSONResponse({'error':str(error)},status_code=401)
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

    @app.get('/api/status')
    def status(request:Request):
        kind=settings.get('DB_KIND','demo')
        return {'version':APP_VERSION,'database':kind,'source':settings.source_label,'previews':kind in ('demo','csv'),
                'model':settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or 'Not configured',
                'model_source':settings.source_of('LLM_MODEL_NAME') if hasattr(settings,'source_of') else 'default','endpoint_source':settings.source_of('LLM_API_URL') if hasattr(settings,'source_of') else 'default',
                'cache_seconds':app.state.snapshots.seconds,'snapshot_at':app.state.snapshots.loaded_at,'qualification':app.state.acceptance.qualification(request.state.owner)}

    @app.get('/api/sessions')
    def sessions(request:Request): return {'sessions':app.state.store.list(request.state.owner)}

    @app.post('/api/sessions')
    def new_session(request:Request): return {'session_id':app.state.store.create(request.state.owner)}

    @app.get('/api/sessions/{session_id}')
    def session(request:Request,session_id:str): return app.state.store.read(request.state.owner,session_id)

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
            values={'grain':'opportunity' if payload.view=='summary' else 'opportunity_sku','intent':payload.intent}
            if payload.intent!='table': values.update(dimensions=['stage_group'],measures=['amount','opportunity_count'])
            if payload.intent=='chart': values['chart_type']='bar'
            return complete(owner,session_id,f'Preview {payload.intent} ({payload.view}) from {settings.source_label}.',parse_plan(values))
        finally: lane.release()

    @app.post('/api/rerun')
    def rerun(request:Request,payload:SessionRequest):
        _,plan=app.state.store.context(request.state.owner,payload.session_id)
        if plan is None: raise AppError('This conversation has no completed query yet.')
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
    def test_start(request:Request,payload:RunRequest): return app.state.acceptance.start(request.state.owner,payload.only_failed_from)

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

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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app_config import APP_VERSION, ROOT, AppError, verify_release
from data_layer import DataRepository
from history_store import HistoryStore
from query_engine import QUERY_FIELDS, PlannerClient, QueryExecutor, merge_plan, parse_plan
from query_models import Intent


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
    lane=threading.Lock()

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

    @app.get('/api/status')
    def status():
        kind=settings.get('DB_KIND','demo')
        return {'version':APP_VERSION,'database':kind,'source':settings.source_label,'previews':kind in ('demo','csv'),
                'model':settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or 'Not configured',
                'cache_seconds':app.state.snapshots.seconds,'snapshot_at':app.state.snapshots.loaded_at}

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
            history,previous=app.state.store.context(owner,session_id)
            incoming=app.state.planner.plan(payload.question.strip(),history,previous,payload.view)
            if set(incoming.remove_filters)-QUERY_FIELDS:
                raise AppError('Unknown field in remove_filters.')
            plan=merge_plan(previous,incoming)
            if plan.intent==Intent.CLARIFY:
                app.state.store.append(owner,session_id,payload.question,plan.clarification)
                return {'kind':'clarify','question':plan.clarification,'suggestions':plan.suggestions,'session_id':session_id}
            return complete(owner,session_id,payload.question,plan)
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

    @app.post('/api/refresh')
    def refresh():
        views,timestamp=app.state.snapshots.get(force=True)
        return {'snapshot_at':timestamp,'source':views.source,'source_name':views.source_name,'opportunities':len(views.opportunity),'skus':len(views.sku)}

    return app

from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor,Request,build_opener,ProxyHandler

import uvicorn
from app_config import AppError,Settings
from data_layer import build_canonical_views,demo_rows
from query_engine import PlannerClient,parse_plan
from ui_app import create_app

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_csv_source import fixture_rows,write_export


class LocalServer:
    """One persistent app process per test class, reached over loopback HTTP like the browser does."""
    def __init__(self,settings,repository=None,planner=None,name='Test Person'):
        self.sock=socket.socket();self.sock.bind(('127.0.0.1',0));self.port=self.sock.getsockname()[1]
        settings.values['APP_PORT']=str(self.port);settings.values.setdefault('B2B_ALLOW_LOCALHOST_IDENTITY','true')
        self.app=create_app(settings,repository=repository,planner=planner)
        self.server=uvicorn.Server(uvicorn.Config(self.app,log_level='critical',access_log=False,proxy_headers=False))
        self.worker=threading.Thread(target=self.server.run,kwargs={'sockets':[self.sock]},daemon=True);self.worker.start()
        deadline=time.monotonic()+5
        while not self.server.started and time.monotonic()<deadline:time.sleep(.01)
        if not self.server.started:raise RuntimeError('Test API failed to start')
        self.base=f'http://127.0.0.1:{self.port}';self.opener=build_opener(ProxyHandler({}),HTTPCookieProcessor())
        # Name identity is the default: log in like the browser does so owner-scoped calls work.
        if settings.get('B2B_IDENTITY','name')=='name' and name:self.login(name)
    def login(self,name):return self.request('/api/login',{'name':name})
    def stop(self):self.server.should_exit=True;self.worker.join(5);self.sock.close()
    def request(self,path,body=None,**headers):
        request=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}|headers)
        with self.opener.open(request,timeout=10) as response:return json.load(response)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        views=build_canonical_views(demo_rows());views.source,views.source_name='demo','fictional demo data'
        cls.repository=MagicMock();cls.repository.load.return_value=views
        cls.planner=MagicMock();cls.planner.plan.return_value=parse_plan({})
        cls.local=LocalServer(Settings(Path(cls.temp.name),{'DB_KIND':'demo'}),repository=cls.repository,planner=cls.planner)
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def request(self,path,body=None,**headers):return self.local.request(path,body,**headers)
    def test_sample_and_saved_query_roundtrip(self):
        result=self.request('/api/sample',{'view':'summary'})
        self.assertEqual(result['table']['rows'][0]['opportunity_amount'],'750')
        saved=self.request('/api/sessions/'+result['session_id'])
        self.assertEqual(saved['active_plan']['grain'],'opportunity')
        self.assertEqual(saved['turns'][0]['question'],'Preview: summary table')
        rerun=self.request('/api/rerun',{'session_id':result['session_id']})
        self.assertEqual(rerun['table']['rows'],result['table']['rows'])
    def test_status_labels_source_and_previews(self):
        status=self.request('/api/status')
        self.assertEqual((status['database'],status['source'],status['previews'],status['version']),('demo','Fictional sample data',True,'0.5.1'))
    def test_clarification_never_loads_sql_or_erases_plan(self):
        first=self.request('/api/sample',{'view':'detail'})
        before=self.repository.load.call_count
        with patch.object(self.planner,'plan',return_value=parse_plan({'intent':'clarify','clarification':'Which date?'})):
            reply=self.request('/api/ask',{'question':'recent ones','session_id':first['session_id']})
        self.assertEqual(reply['kind'],'clarify');self.assertEqual(self.repository.load.call_count,before)
        self.assertEqual(self.request('/api/sessions/'+first['session_id'])['active_plan']['grain'],'opportunity_sku')
    def test_deal_size_vocabulary_and_unknown_fields_in_follow_ups(self):
        first=self.request('/api/sample',{'view':'summary'})
        with patch.object(self.planner,'plan',return_value=parse_plan({'context_action':'refine','intent':'metric','dimensions':['first_channel'],'measures':['deal_size'],'remove_filters':['deal_size']})):
            reply=self.request('/api/ask',{'question':'deal size by channel','session_id':first['session_id']})
        self.assertEqual(reply['table']['columns'],['first_channel','deal_size'])
        with patch.object(self.planner,'plan',return_value=parse_plan({'context_action':'refine','remove_filters':['password']})),self.assertRaises(HTTPError) as error:
            self.request('/api/ask',{'question':'drop it','session_id':first['session_id']})
        self.assertEqual(error.exception.code,400)
    def test_foreign_origin_and_client_history_rejected(self):
        for body,headers,code in [({'view':'summary'},{'Origin':'https://elsewhere.example'},403),({'question':'hello','history':[]},{},400)]:
            with self.assertRaises(HTTPError) as error:self.request('/api/ask',body,**headers)
            self.assertEqual(error.exception.code,code)
    def test_browser_identity_header_cannot_switch_owner(self):
        first=self.request('/api/sessions')
        spoofed=self.request('/api/sessions',None,**{'X-Forwarded-User':'someone-else'})
        self.assertEqual(first,spoofed)
    def test_browser_refresh_route_is_gone(self):
        # Dataset loading is server managed; there is no ordinary refresh endpoint any more.
        with self.assertRaises(HTTPError) as error:self.request('/api/refresh',{})
        self.assertIn(error.exception.code,(404,405))


class CsvModeTests(unittest.TestCase):
    """CSV mode uses the real repository against a synthetic export in the configuration folder."""
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.home=Path(cls.temp.name)
        (cls.home/'exports').mkdir();write_export(cls.home/'exports/salesforce.csv',fixture_rows())
        cls.planner=MagicMock();cls.planner.plan.return_value=parse_plan({'intent':'metric','measures':['deal_size','opportunity_count']})
        cls.local=LocalServer(Settings(cls.home,{'DB_KIND':'csv','B2B_CSV_PATH':'exports/salesforce.csv','B2B_CACHE_SECONDS':'0'}),planner=cls.planner)
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def request(self,path,body=None,**headers):return self.local.request(path,body,**headers)
    def test_status_and_previews_without_qwen(self):
        status=self.request('/api/status')
        self.assertEqual((status['database'],status['source'],status['previews']),('csv','CSV file salesforce.csv',True))
        before=self.planner.plan.call_count
        summary=self.request('/api/sample',{'view':'summary'})
        self.assertEqual(summary['table']['source'],'csv');self.assertEqual(summary['table']['source_name'],'salesforce.csv')
        self.assertEqual(summary['table']['total_rows'],4);self.assertIn('opportunity_amount',summary['table']['columns'])
        detail=self.request('/api/sample',{'view':'detail','session_id':summary['session_id']})
        self.assertEqual(detail['table']['total_rows'],5);self.assertEqual(detail['table']['view'],'detail')
        chart=self.request('/api/sample',{'view':'summary','intent':'chart','session_id':summary['session_id']})
        self.assertEqual(chart['table']['chart']['type'],'bar')
        self.assertEqual(self.planner.plan.call_count,before)
        self.assertEqual(self.request('/api/sessions/'+summary['session_id'])['turns'][0]['question'],'Preview: summary table')
    def test_questions_still_use_the_configured_model(self):
        before=self.planner.plan.call_count
        reply=self.request('/api/ask',{'question':'total deal size'})
        self.assertEqual(self.planner.plan.call_count,before+1)
        self.assertEqual(reply['table']['rows'],[{'deal_size':'1260.50','opportunity_count':4}])
    def test_server_managed_snapshot_rereads_the_file_and_reports_errors(self):
        # With a zero cache the next question reads the current file; load failures are reported, never hidden.
        self.assertEqual(self.request('/api/sample',{'view':'summary'})['table']['total_rows'],4)
        path=self.home/'exports/salesforce.csv';original=path.read_bytes()
        try:
            write_export(path,fixture_rows()[:3])
            self.assertEqual(self.request('/api/sample',{'view':'summary'})['table']['total_rows'],1)
            path.write_text('broken header only\n',encoding='utf-8')
            with self.assertRaises(HTTPError) as error:self.request('/api/sample',{'view':'summary'})
            self.assertEqual(error.exception.code,400);self.assertIn('missing required Salesforce columns',json.load(error.exception)['error'])
        finally:path.write_bytes(original)
        self.assertEqual(self.request('/api/sample',{'view':'summary'})['table']['total_rows'],4)


class PostgresModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        repository=MagicMock();repository.load.return_value=build_canonical_views(demo_rows())
        cls.local=LocalServer(Settings(Path(cls.temp.name),{'DB_KIND':'postgres','PGURL':'database.example:5432/postgres','B2B_CSV_PATH':'ignored.csv'}),repository=repository,planner=MagicMock())
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def test_previews_are_not_offered_for_the_shared_database(self):
        status=self.local.request('/api/status')
        self.assertEqual((status['database'],status['source'],status['previews']),('postgres','PostgreSQL bi_reporting.b2b_project',False))
        with self.assertRaises(HTTPError) as error:self.local.request('/api/sample',{'view':'summary'})
        self.assertEqual(error.exception.code,400)


class PlannerProtocolTests(unittest.TestCase):
    def test_full_endpoint_and_no_secrets_in_prompt(self):
        captured=[]
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));captured.append((self.path,payload))
                content=json.dumps({'intent':'table','filters':[]})
                response={'message':{'content':content}} if self.path=='/api/chat' else {'choices':[{'message':{'content':content}}]}
                data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Stub);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            for provider,suffix in [('openai_compatible','/v1/chat/completions'),('ollama','/api/chat')]:
                settings=Settings(Path('.'),{'AI_PROVIDER':provider,'LLM_MODEL_NAME':'test-qwen','LLM_API_URL':f'http://127.0.0.1:{server.server_address[1]}'+suffix,'RO_SQL_PW':'db-secret','LLM_API_KEY':'model-secret'})
                self.assertEqual(PlannerClient(settings).plan('Show deals',[]).intent.value,'table')
                self.assertEqual(captured[-1][0],suffix)
                prompt=json.dumps(captured[-1][1])
                self.assertNotIn('db-secret',prompt);self.assertNotIn('model-secret',prompt)
                for word in ('deal_size','first_channel','deal_size_on_pricing_date_usd','once per opportunity','exactly one JSON object','Greetings, small talk'):self.assertIn(word,prompt)
                if provider=='openai_compatible':
                    self.assertEqual(set(captured[-1][1]),{'model','messages','stream','temperature','max_tokens'});self.assertTrue(captured[-1][1]['stream'])
        finally:server.shutdown();server.server_close();worker.join()


class AcceptanceApiTests(unittest.TestCase):
    """The owner-scoped test APIs drive the suite with a scripted model over HTTP."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from acceptance_fixture import ScriptedPlanner,synthetic_records
        from acceptance_suite import select_witnesses
        from reference_evaluator import ReferenceSource
        cls.temp=tempfile.TemporaryDirectory();cls.home=Path(cls.temp.name)
        cls.records=synthetic_records();witnesses=select_witnesses(ReferenceSource(cls.records),cls.records)[0]
        repository=MagicMock();frame=__import__('pandas').DataFrame(cls.records,columns=__import__('data_layer').RAW_COLUMNS,dtype=object)
        repository.load_raw.side_effect=lambda:(frame.copy(),'postgres','test.b2b_project')
        repository.load.side_effect=lambda:__import__('data_layer').build_canonical_views(frame.copy())
        cls.local=LocalServer(Settings(cls.home,{'DB_KIND':'postgres','PGURL':'db.example:5432/postgres','LLM_MODEL_NAME':'qwen-test','B2B_ENABLE_ACCEPTANCE_UI':'true'}),repository=repository,planner=ScriptedPlanner(witnesses))
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def request(self,path,body=None,**headers):return self.local.request(path,body,**headers)
    def test_suite_manifest_and_full_run_over_http(self):
        suite=self.request('/api/test/suite');self.assertGreaterEqual(len(suite['steps']),54);total=len(suite['steps']);self.assertEqual(len(suite['browser_checks']),16);self.assertFalse(suite['qualification']['ready'])
        started=self.request('/api/test/runs',{});run_id=started['run']['id'];self.assertEqual(started['next_step'],0)
        with self.assertRaises(HTTPError) as error:self.request('/api/test/runs',{});self.assertEqual(error.exception.code,400)
        for body in [{'step':5},{'step':-1},{'prompt':'Show everything','step':0},{'step':0,'plan':{}}]:
            with self.subTest(body=body),self.assertRaises(HTTPError) as error:self.request(f'/api/test/runs/{run_id}/step',body)
            self.assertEqual(error.exception.code,400)
        first=self.request(f'/api/test/runs/{run_id}/step',{'step':0})
        self.assertEqual(first['step']['status'],'pass');self.assertIn('rows',first['table']);self.assertEqual(first['table']['total_rows'],60)
        again=self.request(f'/api/test/runs/{run_id}/step',{'step':0});self.assertEqual(again['step']['seconds'],first['step']['seconds'])
        for index in range(1,total):self.request(f'/api/test/runs/{run_id}/step',{'step':index})
        with self.assertRaises(HTTPError):self.request(f'/api/test/runs/{run_id}/step',{'step':total})
        for check in range(1,17):self.request(f'/api/test/runs/{run_id}/browser',{'check':check,'status':'pass','expected':{'x':1},'observed':{'x':1},'notes':'ok'})
        status=self.request(f'/api/test/runs/{run_id}');self.assertEqual(status['run']['status'],'complete');self.assertTrue(status['full_pass']);self.assertTrue(status['comparison'] is None or 'previous_run' in status['comparison'])
        detail=self.request(f'/api/test/runs/{run_id}/steps/T25');self.assertEqual(len(detail['result']['rows']),10);self.assertTrue(detail['data']['ok'])
        request=Request(self.local.base+f'/api/test/runs/{run_id}/report')
        with self.local.opener.open(request,timeout=10) as response:
            self.assertEqual(response.headers['Content-Type'],'text/markdown; charset=utf-8');self.assertIn('attachment; filename="b2b-test-',response.headers['Content-Disposition'])
            report=response.read().decode('utf-8')
        self.assertIn('## Scorecard',report);self.assertIn('Full pass: **yes**',report)
        listed=self.request('/api/test/runs');self.assertEqual(listed['runs'][0]['id'],run_id);self.assertTrue(listed['runs'][0]['full_pass'])
        self.assertEqual(self.request('/api/status')['qualification']['streak'],1)
        with self.assertRaises(HTTPError) as error:self.request('/api/test/runs/'+'0'*32)
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(HTTPError):self.request(f'/api/test/runs/{run_id}/step',{'step':total})
    def test_cancel_over_http_and_ordinary_questions_share_the_lane(self):
        started=self.request('/api/test/runs',{});run_id=started['run']['id']
        self.request(f'/api/test/runs/{run_id}/step',{'step':0})
        cancelled=self.request(f'/api/test/runs/{run_id}/cancel',{});self.assertEqual(cancelled['run']['status'],'cancelled')
        with self.assertRaises(HTTPError):self.request(f'/api/test/runs/{run_id}/step',{'step':1})
        self.assertEqual(self.request('/api/sessions')['sessions'],[])   # test conversations never appear in saved history


class PlannerFailureTests(unittest.TestCase):
    """Model failures name the cause without the key; servers without response_format support still work."""
    def serve(self,handler):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        return server,worker
    def settings(self,port,**extra):
        return Settings(Path('.'),{'AI_PROVIDER':'openai_compatible','LLM_MODEL_NAME':'test-qwen','LLM_API_URL':f'http://127.0.0.1:{port}/v1/chat/completions','LLM_API_KEY':'model-secret'}|extra)
    def test_http_error_and_bad_shape_are_explained(self):
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                if self.path.endswith('/v1/chat/completions'):data=b'{"error":{"message":"model test-qwen not found; key model-secret"}}';self.send_response(404)
                else:data=b'<html>not an api</html>';self.send_response(200)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server,worker=self.serve(Stub)
        try:
            with self.assertRaises(AppError) as error:PlannerClient(self.settings(server.server_address[1])).plan('Show deals',[])
            text=str(error.exception);self.assertIn('HTTP 404',text);self.assertIn('model test-qwen not found',text);self.assertNotIn('model-secret',text);self.assertIn(f"127.0.0.1:{server.server_address[1]}",text)
            with self.assertRaises(AppError) as error:PlannerClient(self.settings(server.server_address[1],LLM_API_URL=f'http://127.0.0.1:{server.server_address[1]}/other/chat/completions')).plan('Show deals',[])
            self.assertIn('not with an OpenAI-style chat completion',str(error.exception))
        finally:server.shutdown();server.server_close();worker.join()
        with self.assertRaises(AppError) as error:PlannerClient(self.settings(1)).plan('Show deals',[])
        self.assertIn('could not be reached',str(error.exception))
    def test_wrapped_json_reply_is_parsed_without_response_format(self):
        seen=[]
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(payload)
                if 'response_format' in payload:
                    data=b'{"error":"response_format is not supported by this server"}';self.send_response(400)
                else:
                    content='<think>reasoning here</think>Sure! ```json\n{"intent":"table","filters":[{"field":"stage","operator":"eq","value":"Won"}]}\n``` Done.'
                    data=json.dumps({'choices':[{'message':{'content':content}}]}).encode();self.send_response(200)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server,worker=self.serve(Stub)
        try:
            plan=PlannerClient(self.settings(server.server_address[1])).plan('Show won deals',[])
            # response_format is never sent (Scribble-style payload), so the wrapped JSON is parsed on the first reply.
            self.assertEqual(plan.filters[0].value,'Won');self.assertEqual(len(seen),1);self.assertNotIn('response_format',seen[0])
        finally:server.shutdown();server.server_close();worker.join()
    def test_streamed_reply_and_temperature_rejection(self):
        seen=[]
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(payload)
                if 'temperature' in payload:
                    data=b'{"error":{"message":"temperature is not supported for this model"}}';self.send_response(400);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                chunks=['{"intent":"table",','"filters":[{"field":"stage",','"operator":"eq","value":"Won"}]}']
                data=''.join('data: '+json.dumps({'choices':[{'delta':{'content':c}}]})+'\n\n' for c in chunks)+'data: [DONE]\n\n'
                data=data.encode();self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server,worker=self.serve(Stub)
        try:
            plan=PlannerClient(self.settings(server.server_address[1])).plan('Show won deals',[])
            self.assertEqual(plan.filters[0].value,'Won');self.assertEqual(len(seen),2);self.assertNotIn('temperature',seen[1]);self.assertTrue(seen[1]['stream'])
        finally:server.shutdown();server.server_close();worker.join()
    def test_prose_reply_becomes_a_clarification(self):
        replies=iter(["Hello! I'm ready to help you query your Salesforce opportunity data.\n\nWhat would you like to look at? Here are a few examples:\n* \"Show me a summary of all open opportunities.\"\n* \"What are the top opportunities by amount?\"\n* \"Break down open deals by stage or owner.\"\nJust ask and I will translate it into a plan for you right away, whenever you are ready to begin exploring the data together.",
                      "<think>a greeting, not a question</think>I'm ready when you are. What would you like to explore?"])
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                data=json.dumps({'choices':[{'message':{'content':next(replies)}}]}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server,worker=self.serve(Stub)
        try:
            client=PlannerClient(self.settings(server.server_address[1]))
            plan=client.plan('hey',[])
            self.assertEqual(plan.intent.value,'clarify');self.assertTrue(plan.clarification.startswith("Hello! I'm ready to help"));self.assertLessEqual(len(plan.clarification),300);self.assertNotIn('\n',plan.clarification);self.assertNotIn('* ',plan.clarification)
            plan=client.plan('yeheyhey',[])
            self.assertEqual((plan.intent.value,plan.clarification),('clarify',"I'm ready when you are. What would you like to explore?"))
        finally:server.shutdown();server.server_close();worker.join()
    def test_invalid_plan_names_the_problem(self):
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                data=json.dumps({'choices':[{'message':{'content':'{"intent":"dance","limit":"ten"}'}}]}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server,worker=self.serve(Stub)
        try:
            with self.assertRaises(AppError) as error:PlannerClient(self.settings(server.server_address[1])).plan('Show deals',[])
            self.assertIn('intent',str(error.exception));self.assertIn('dance',str(error.exception))
        finally:server.shutdown();server.server_close();worker.join()


class IdentityAndLogTests(unittest.TestCase):
    """Name identity, the login/activity log with IP addresses, per-person history with model replies."""
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.home=Path(cls.temp.name)
        views=build_canonical_views(demo_rows());views.source,views.source_name='demo','fictional demo data'
        repository=MagicMock();repository.load.return_value=views
        cls.planner=MagicMock();cls.planner.plan.return_value=parse_plan({'filters':[{'field':'stage','operator':'eq','value':'Won'}]})
        cls.local=LocalServer(Settings(cls.home,{'DB_KIND':'demo'}),repository=repository,planner=cls.planner,name=None)
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def request(self,path,body=None,**headers):return self.local.request(path,body,**headers)
    def test_login_is_required_then_logged_with_ip_and_history_is_per_person(self):
        me=self.request('/api/me');self.assertTrue(me['login_required']);self.assertEqual(me['ip'],'127.0.0.1')
        with self.assertRaises(HTTPError) as error:self.request('/api/sessions')
        self.assertEqual(error.exception.code,401);self.assertTrue(json.load(error.exception)['login_required'])
        status=self.request('/api/status');self.assertIsNone(status['qualification'])
        for bad in ['   ','x'*61,'bad\x01name']:
            with self.subTest(bad=bad),self.assertRaises(HTTPError):self.request('/api/login',{'name':bad})
        self.assertEqual(self.request('/api/login',{'name':'  Ana   Lima '})['name'],'Ana Lima')
        me=self.request('/api/me');self.assertEqual((me['login_required'],me['name'],me['owner']),(False,'Ana Lima','name:Ana Lima'))
        asked=self.request('/api/ask',{'question':'won deals please'})
        saved=self.request('/api/sessions/'+asked['session_id'])
        self.assertEqual(saved['turns'][0]['model_reply']['filters'][0]['value'],'Won');self.assertTrue(saved['turns'][0]['response'].startswith('Table (opportunity summary): 2 rows'))
        shown=self.request(f"/api/sessions/{asked['session_id']}/turns/{saved['turns'][0]['id']}/run",{})
        self.assertEqual(shown['table']['total_rows'],2)
        store=self.local.app.state.store;log=store.access_log()
        self.assertEqual([(l['name'],l['ip']) for l in log['logins']],[('Ana Lima','127.0.0.1')]);self.assertEqual(log['users'][0]['logins'],1)
        kinds=[(a['kind'],a['owner'],a['ip']) for a in log['activity']]
        self.assertIn(('ask','name:Ana Lima','127.0.0.1'),kinds);self.assertIn(('rerun','name:Ana Lima','127.0.0.1'),kinds)
        self.assertEqual(next(a for a in log['activity'] if a['kind']=='ask')['detail'],'won deals please')
        self.assertTrue((self.home/'data/history.sqlite3').exists());self.assertTrue((self.home/'data/.cookie_secret').exists())
        # Another person sees their own list only; renaming and deleting are owner scoped.
        self.request('/api/logout',{});self.request('/api/login',{'name':'Bo Berg'})
        self.assertEqual(self.request('/api/sessions')['sessions'],[])
        with self.assertRaises(HTTPError):self.request('/api/sessions/'+asked['session_id'])
        self.request('/api/logout',{});self.request('/api/login',{'name':'Ana Lima'})
        self.assertEqual(len(self.request('/api/sessions')['sessions']),1);self.assertEqual(store.access_log()['users'][0]['logins'],2)
        self.request(f"/api/sessions/{asked['session_id']}/title",{'title':'Won deals'})
        self.assertEqual(self.request('/api/sessions')['sessions'][0]['title'],'Won deals')
        request=Request(self.local.base+'/api/sessions/'+asked['session_id'],method='DELETE')
        with self.local.opener.open(request,timeout=10) as response:self.assertTrue(json.load(response)['ok'])
        self.assertEqual(self.request('/api/sessions')['sessions'],[])
    def test_forged_cookie_is_ignored(self):
        request=Request(self.local.base+'/api/me',headers={'Cookie':'b2b_user=QW5h.deadbeef'})
        with build_opener(ProxyHandler({})).open(request,timeout=10) as response:self.assertTrue(json.load(response)['login_required'])


class WindowsIdentityAndLanTests(unittest.TestCase):
    def test_windows_identity_needs_no_login_and_lan_hosts_are_accepted_same_origin(self):
        temp=tempfile.TemporaryDirectory();home=Path(temp.name)
        repository=MagicMock();repository.load.return_value=build_canonical_views(demo_rows())
        local=LocalServer(Settings(home,{'DB_KIND':'demo','B2B_IDENTITY':'windows','B2B_LISTEN_HOST':'0.0.0.0'}),repository=repository,planner=MagicMock(),name=None)
        try:
            me=local.request('/api/me');self.assertFalse(me['login_required']);self.assertTrue(me['owner'].startswith('local:'))
            request=Request(local.base+'/api/sessions',headers={'Host':f'workpc.corp:{local.port}','Origin':f'http://workpc.corp:{local.port}'})
            with local.opener.open(request,timeout=10) as response:self.assertIn('sessions',json.load(response))
            with self.assertRaises(HTTPError) as error:
                local.opener.open(Request(local.base+'/api/sessions',headers={'Host':f'workpc.corp:{local.port}','Origin':'http://evil.example'}),timeout=10)
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError) as error:local.opener.open(Request(local.base+'/api/sessions',headers={'Host':'workpc.corp:9999'}),timeout=10)
            self.assertEqual(error.exception.code,403)
        finally:local.stop();temp.cleanup()

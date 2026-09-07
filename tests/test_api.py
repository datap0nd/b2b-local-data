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
from urllib.request import Request,build_opener,ProxyHandler

import uvicorn
from app_config import AppError,Settings
from data_layer import build_canonical_views,demo_rows
from query_engine import PlannerClient,parse_plan
from ui_app import create_app

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_csv_source import fixture_rows,write_export


class LocalServer:
    """One persistent app process per test class, reached over loopback HTTP like the browser does."""
    def __init__(self,settings,repository=None,planner=None):
        self.sock=socket.socket();self.sock.bind(('127.0.0.1',0));self.port=self.sock.getsockname()[1]
        settings.values['APP_PORT']=str(self.port);settings.values.setdefault('B2B_ALLOW_LOCALHOST_IDENTITY','true')
        self.app=create_app(settings,repository=repository,planner=planner)
        self.server=uvicorn.Server(uvicorn.Config(self.app,log_level='critical',access_log=False,proxy_headers=False))
        self.worker=threading.Thread(target=self.server.run,kwargs={'sockets':[self.sock]},daemon=True);self.worker.start()
        deadline=time.monotonic()+5
        while not self.server.started and time.monotonic()<deadline:time.sleep(.01)
        if not self.server.started:raise RuntimeError('Test API failed to start')
        self.base=f'http://127.0.0.1:{self.port}';self.opener=build_opener(ProxyHandler({}))
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
        self.assertEqual(saved['turns'][0]['question'],'Preview table (summary) from Fictional sample data.')
        rerun=self.request('/api/rerun',{'session_id':result['session_id']})
        self.assertEqual(rerun['table']['rows'],result['table']['rows'])
    def test_status_labels_source_and_previews(self):
        status=self.request('/api/status')
        self.assertEqual((status['database'],status['source'],status['previews'],status['version']),('demo','Fictional sample data',True,'0.5.0'))
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
    def test_refresh_does_not_call_qwen(self):
        before=self.planner.plan.call_count;result=self.request('/api/refresh',{})
        self.assertEqual(self.planner.plan.call_count,before);self.assertEqual(result['source'],'demo')


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
        self.assertEqual(self.request('/api/sessions/'+summary['session_id'])['turns'][0]['question'],'Preview table (summary) from CSV file salesforce.csv.')
    def test_questions_still_use_the_configured_model(self):
        before=self.planner.plan.call_count
        reply=self.request('/api/ask',{'question':'total deal size'})
        self.assertEqual(self.planner.plan.call_count,before+1)
        self.assertEqual(reply['table']['rows'],[{'deal_size':'1260.50','opportunity_count':4}])
    def test_refresh_rereads_the_file_and_reports_errors(self):
        result=self.request('/api/refresh',{})
        self.assertEqual((result['source'],result['source_name'],result['opportunities'],result['skus']),('csv','salesforce.csv',4,5))
        path=self.home/'exports/salesforce.csv';original=path.read_bytes()
        try:
            write_export(path,fixture_rows()[:3])
            self.assertEqual(self.request('/api/refresh',{})['opportunities'],1)
            path.write_text('broken header only\n',encoding='utf-8')
            with self.assertRaises(HTTPError) as error:self.request('/api/refresh',{})
            self.assertEqual(error.exception.code,400);self.assertIn('missing required Salesforce columns',json.load(error.exception)['error'])
        finally:path.write_bytes(original)
        self.assertEqual(self.request('/api/refresh',{})['opportunities'],4)


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
                for word in ('deal_size','first_channel','deal_size_on_pricing_date_usd','once per opportunity'):self.assertIn(word,prompt)
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
        cls.local=LocalServer(Settings(cls.home,{'DB_KIND':'postgres','PGURL':'db.example:5432/postgres','LLM_MODEL_NAME':'qwen-test'}),repository=repository,planner=ScriptedPlanner(witnesses))
    @classmethod
    def tearDownClass(cls):cls.local.stop();cls.temp.cleanup()
    def request(self,path,body=None,**headers):return self.local.request(path,body,**headers)
    def test_suite_manifest_and_full_run_over_http(self):
        suite=self.request('/api/test/suite');self.assertEqual(len(suite['steps']),54);self.assertEqual(len(suite['browser_checks']),12);self.assertFalse(suite['qualification']['ready'])
        started=self.request('/api/test/runs',{});run_id=started['run']['id'];self.assertEqual(started['next_step'],0)
        with self.assertRaises(HTTPError) as error:self.request('/api/test/runs',{});self.assertEqual(error.exception.code,400)
        for body in [{'step':5},{'step':-1},{'prompt':'Show everything','step':0},{'step':0,'plan':{}}]:
            with self.subTest(body=body),self.assertRaises(HTTPError) as error:self.request(f'/api/test/runs/{run_id}/step',body)
            self.assertEqual(error.exception.code,400)
        first=self.request(f'/api/test/runs/{run_id}/step',{'step':0})
        self.assertEqual(first['step']['status'],'pass');self.assertIn('rows',first['table']);self.assertEqual(first['table']['total_rows'],60)
        again=self.request(f'/api/test/runs/{run_id}/step',{'step':0});self.assertEqual(again['step']['seconds'],first['step']['seconds'])
        for index in range(1,54):self.request(f'/api/test/runs/{run_id}/step',{'step':index})
        with self.assertRaises(HTTPError):self.request(f'/api/test/runs/{run_id}/step',{'step':54})
        for check in range(1,13):self.request(f'/api/test/runs/{run_id}/browser',{'check':check,'status':'pass','expected':{'x':1},'observed':{'x':1},'notes':'ok'})
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
        with self.assertRaises(HTTPError):self.request(f'/api/test/runs/{run_id}/step',{'step':54})
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
    def test_response_format_rejection_falls_back_and_wrapped_json_is_parsed(self):
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
            self.assertEqual(plan.filters[0].value,'Won');self.assertEqual(len(seen),2);self.assertNotIn('response_format',seen[1])
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

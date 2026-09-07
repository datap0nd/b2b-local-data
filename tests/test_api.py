from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler

import uvicorn
from app_config import Settings
from data_layer import build_canonical_views,demo_rows
from query_engine import PlannerClient,parse_plan
from ui_app import create_app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.sock=socket.socket();cls.sock.bind(('127.0.0.1',0))
        port=cls.sock.getsockname()[1]
        settings=Settings(Path(cls.temp.name),{'DB_KIND':'demo','APP_PORT':str(port),'B2B_ALLOW_LOCALHOST_IDENTITY':'true'})
        cls.repository=MagicMock();cls.repository.load.return_value=build_canonical_views(demo_rows())
        cls.planner=MagicMock();cls.planner.plan.return_value=parse_plan({})
        cls.app=create_app(settings,repository=cls.repository,planner=cls.planner)
        cls.server=uvicorn.Server(uvicorn.Config(cls.app,log_level='critical',access_log=False,proxy_headers=False))
        cls.worker=threading.Thread(target=cls.server.run,kwargs={'sockets':[cls.sock]},daemon=True);cls.worker.start()
        deadline=time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline:time.sleep(.01)
        if not cls.server.started:raise RuntimeError('Test API failed to start')
        cls.base=f'http://127.0.0.1:{port}';cls.opener=build_opener(ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.worker.join(5);cls.sock.close();cls.temp.cleanup()
    def request(self,path,body=None,**headers):
        request=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}|headers)
        with self.opener.open(request,timeout=10) as response:return json.load(response)
    def test_sample_and_saved_query_roundtrip(self):
        result=self.request('/api/sample',{'view':'summary'})
        self.assertEqual(result['table']['rows'][0]['opportunity_amount'],'750')
        saved=self.request('/api/sessions/'+result['session_id'])
        self.assertEqual(saved['active_plan']['grain'],'opportunity')
        rerun=self.request('/api/rerun',{'session_id':result['session_id']})
        self.assertEqual(rerun['table']['rows'],result['table']['rows'])
    def test_clarification_never_loads_sql_or_erases_plan(self):
        first=self.request('/api/sample',{'view':'detail'})
        before=self.repository.load.call_count
        with patch.object(self.planner,'plan',return_value=parse_plan({'intent':'clarify','clarification':'Which date?'})):
            reply=self.request('/api/ask',{'question':'recent ones','session_id':first['session_id']})
        self.assertEqual(reply['kind'],'clarify');self.assertEqual(self.repository.load.call_count,before)
        self.assertEqual(self.request('/api/sessions/'+first['session_id'])['active_plan']['grain'],'opportunity_sku')
    def test_foreign_origin_and_client_history_rejected(self):
        for body,headers,code in [({'view':'summary'},{'Origin':'https://elsewhere.example'},403),({'question':'hello','history':[]},{},400)]:
            with self.assertRaises(HTTPError) as error:self.request('/api/ask',body,**headers)
            self.assertEqual(error.exception.code,code)
    def test_browser_identity_header_cannot_switch_owner(self):
        first=self.request('/api/sessions')
        spoofed=self.request('/api/sessions',None,**{'X-Forwarded-User':'someone-else'})
        self.assertEqual(first,spoofed)
    def test_refresh_does_not_call_qwen(self):
        before=self.planner.plan.call_count;self.request('/api/refresh',{})
        self.assertEqual(self.planner.plan.call_count,before)


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
                self.assertNotIn('db-secret',json.dumps(captured[-1][1]));self.assertNotIn('model-secret',json.dumps(captured[-1][1]))
        finally:server.shutdown();server.server_close();worker.join()

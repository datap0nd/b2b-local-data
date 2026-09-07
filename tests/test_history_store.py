from pathlib import Path
import tempfile
import unittest

from app_config import AppError
from history_store import HistoryStore
from query_engine import parse_plan


class HistoryTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'history.db';self.store=HistoryStore(self.path)
    def tearDown(self):self.temp.cleanup()
    def test_persistence_and_clarification_do_not_erase_active_plan(self):
        session=self.store.create('alice');plan=parse_plan({'limit':7})
        self.store.append('alice',session,'show deals','7 deals',plan)
        self.store.append('alice',session,'recent ones','Which date?')
        restarted=HistoryStore(self.path);history,active=restarted.context('alice',session)
        self.assertEqual(active.limit,7)
        self.assertEqual(len(history),4)
        self.assertEqual(len(restarted.list('alice')),1)
    def test_sessions_are_owner_scoped(self):
        session=self.store.create('alice')
        self.assertEqual(self.store.list('bob'),[])
        for action in [lambda:self.store.read('bob',session),lambda:self.store.append('bob',session,'x','y')]:
            with self.assertRaises(AppError):action()
    def test_model_history_carries_each_turns_plan(self):
        session=self.store.create('alice');plan=parse_plan({'filters':[{'field':'stage','operator':'eq','value':'Won'}]})
        self.store.append('alice',session,'won deals','Table (opportunity summary): 2 rows · filters: stage eq Won.',plan)
        self.store.append('alice',session,'and next year?','Which date field?')
        history,_=self.store.context('alice',session)
        self.assertIn('"field":"stage"',history[1]['content']);self.assertIn('earlier or unavailable calculations',history[1]['content'])
        self.assertNotIn('2 rows',history[1]['content'])
        self.assertEqual(history[3]['content'],'Which date field?')
    def test_new_session_has_no_query(self):
        self.assertEqual(self.store.context('alice',self.store.create('alice')),([],None))
    def test_version_one_database_gains_model_replies_and_logs(self):
        import sqlite3
        from contextlib import closing
        path=Path(self.temp.name)/'old.db'
        with closing(sqlite3.connect(path)) as connection,connection:
            connection.executescript('''CREATE TABLE sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'New conversation', active_plan TEXT, created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
                CREATE TABLE turns (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), question TEXT NOT NULL, response TEXT NOT NULL, plan TEXT, created_at TEXT NOT NULL DEFAULT '');
                INSERT INTO sessions(id,owner) VALUES ('s1','alice'); INSERT INTO turns(session_id,question,response) VALUES ('s1','old question','old answer'); PRAGMA user_version=1;''')
        store=HistoryStore(path)
        saved=store.read('alice','s1');self.assertIsNone(saved['turns'][0]['model_reply']);self.assertEqual(saved['turns'][0]['question'],'old question')
        store.append('alice','s1','new','answer',parse_plan({'limit':3}),model_reply={'intent':'table','limit':3})
        self.assertEqual(store.read('alice','s1')['turns'][1]['model_reply'],{'intent':'table','limit':3})
        self.assertEqual(store.turn_plan('alice','s1',2).limit,3)
        with self.assertRaises(AppError):store.turn_plan('alice','s1',1)
        store.log_login('alice','10.0.0.5','Browser/1');store.log_login('alice','10.0.0.6','Browser/1');store.log_activity('alice','10.0.0.5','ask','s1','hello')
        log=store.access_log();self.assertEqual(log['users'][0]['logins'],2);self.assertEqual([l['ip'] for l in log['logins']],['10.0.0.6','10.0.0.5']);self.assertEqual(log['activity'][0]['detail'],'hello')
        store.rename('alice','s1','Renamed');self.assertEqual(store.list('alice')[0]['title'],'Renamed')
        store.delete('alice','s1');self.assertEqual(store.list('alice'),[])

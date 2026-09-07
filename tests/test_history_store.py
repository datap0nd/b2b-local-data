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
    def test_new_session_has_no_query(self):
        self.assertEqual(self.store.context('alice',self.store.create('alice')),([],None))

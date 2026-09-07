"""Persistent, owner-scoped SQLite history. Result rows and credentials are not stored."""
import json
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager

from app_config import AppError
from query_engine import parse_plan


class HistoryStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as connection:
            if connection.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
                raise AppError('History schema is newer than this application. Use a compatible release.')
            connection.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'New conversation',
                    active_plan TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), question TEXT NOT NULL,
                    response TEXT NOT NULL, plan TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner,updated_at);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=10)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self,owner):
        session=uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute('INSERT INTO sessions(id,owner) VALUES (?,?)',(session,owner))
        return session

    def _owned(self,connection,owner,session):
        row=connection.execute('SELECT * FROM sessions WHERE id=? AND owner=?',(session,owner)).fetchone()
        if row is None: raise AppError('Conversation not found for this user.')
        return row

    def list(self,owner):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute('SELECT id,title,updated_at FROM sessions WHERE owner=? ORDER BY updated_at DESC,id LIMIT 100',(owner,))]

    def read(self,owner,session):
        with self.connect() as connection:
            info=self._owned(connection,owner,session)
            turns=[dict(row) for row in connection.execute('SELECT id,question,response,plan,created_at FROM (SELECT * FROM turns WHERE session_id=? ORDER BY id DESC LIMIT 100) ORDER BY id',(session,))]
        for row in turns:
            row['plan']=json.loads(row['plan']) if row['plan'] else None
        return {'id':session,'title':info['title'],'turns':turns,'active_plan':json.loads(info['active_plan']) if info['active_plan'] else None}

    def context(self,owner,session):
        saved=self.read(owner,session)
        history=[]
        for turn in saved['turns'][-8:]:
            history.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':turn['response']}])
        return history,parse_plan(saved['active_plan']) if saved['active_plan'] else None

    def append(self,owner,session,question,response,plan=None):
        encoded=plan.model_dump_json() if plan else None
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('INSERT INTO turns(session_id,question,response,plan) VALUES (?,?,?,?)',(session,question,response,encoded))
            connection.execute("UPDATE sessions SET active_plan=COALESCE(?,active_plan),title=CASE WHEN title='New conversation' THEN ? ELSE title END,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(encoded,question[:100],session))

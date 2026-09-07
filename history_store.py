"""Persistent local SQLite store: per-person conversations with every model reply, plus the login and activity log.

Result rows and credentials are never stored. The file lives under B2B_DATA_DIR (the install folder's data\\ directory)."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

from app_config import AppError
from query_engine import parse_plan

SCHEMA_VERSION=2


class HistoryStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as connection:
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version>SCHEMA_VERSION:
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
                CREATE TABLE IF NOT EXISTS users (
                    name TEXT PRIMARY KEY, first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), logins INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS logins (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, ip TEXT NOT NULL, user_agent TEXT,
                    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, ip TEXT NOT NULL, kind TEXT NOT NULL, session_id TEXT, detail TEXT,
                    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE INDEX IF NOT EXISTS activity_owner ON activity(owner,at);
            ''')
            columns={row[1] for row in connection.execute('PRAGMA table_info(turns)')}
            if 'model_reply' not in columns:
                # Version 1 databases gain the raw model reply column; existing turns keep it empty.
                connection.execute('ALTER TABLE turns ADD COLUMN model_reply TEXT')
            connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

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

    # ----- people and the access log -----
    def log_login(self,name,ip,user_agent=None):
        with self.connect() as connection:
            connection.execute("INSERT INTO users(name) VALUES (?) ON CONFLICT(name) DO UPDATE SET last_seen=strftime('%Y-%m-%dT%H:%M:%fZ','now'), logins=logins+1",(name,))
            connection.execute('UPDATE users SET logins=logins+1 WHERE name=? AND logins=0',(name,))
            connection.execute('INSERT INTO logins(name,ip,user_agent) VALUES (?,?,?)',(name,ip,(user_agent or '')[:300]))

    def log_activity(self,owner,ip,kind,session=None,detail=None):
        with self.connect() as connection:
            connection.execute('INSERT INTO activity(owner,ip,kind,session_id,detail) VALUES (?,?,?,?,?)',(owner,ip,kind,session,(detail or '')[:1000]))

    def access_log(self,limit=200):
        with self.connect() as connection:
            logins=[dict(r) for r in connection.execute('SELECT name,ip,user_agent,at FROM logins ORDER BY id DESC LIMIT ?',(limit,))]
            activity=[dict(r) for r in connection.execute('SELECT owner,ip,kind,session_id,detail,at FROM activity ORDER BY id DESC LIMIT ?',(limit,))]
            users=[dict(r) for r in connection.execute('SELECT name,first_seen,last_seen,logins FROM users ORDER BY last_seen DESC')]
        return {'users':users,'logins':logins,'activity':activity}

    # ----- conversations -----
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
            return [dict(row) for row in connection.execute('SELECT id,title,updated_at FROM sessions WHERE owner=? ORDER BY updated_at DESC,id LIMIT 200',(owner,))]

    def read(self,owner,session):
        with self.connect() as connection:
            info=self._owned(connection,owner,session)
            turns=[dict(row) for row in connection.execute('SELECT id,question,response,plan,model_reply,created_at FROM (SELECT * FROM turns WHERE session_id=? ORDER BY id DESC LIMIT 200) ORDER BY id',(session,))]
        for row in turns:
            row['plan']=json.loads(row['plan']) if row['plan'] else None
            row['model_reply']=json.loads(row['model_reply']) if row['model_reply'] else None
        return {'id':session,'title':info['title'],'turns':turns,'active_plan':json.loads(info['active_plan']) if info['active_plan'] else None}

    def context(self,owner,session):
        saved=self.read(owner,session)
        history=[]
        # The model sees each earlier answer together with the plan that produced it, so follow-ups refine real context.
        for turn in saved['turns'][-8:]:
            answer=turn['response']+(('\nPlan: '+json.dumps(turn['plan'],separators=(',',':'))) if turn.get('plan') else '')
            history.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':answer}])
        return history,parse_plan(saved['active_plan']) if saved['active_plan'] else None

    def append(self,owner,session,question,response,plan=None,model_reply=None):
        encoded=plan.model_dump_json() if plan else None
        reply=json.dumps(model_reply,ensure_ascii=False) if model_reply is not None else None
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('INSERT INTO turns(session_id,question,response,plan,model_reply) VALUES (?,?,?,?,?)',(session,question,response,encoded,reply))
            connection.execute("UPDATE sessions SET active_plan=COALESCE(?,active_plan),title=CASE WHEN title='New conversation' THEN ? ELSE title END,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(encoded,question[:100],session))

    def turn_plan(self,owner,session,turn_id):
        with self.connect() as connection:
            self._owned(connection,owner,session)
            row=connection.execute('SELECT plan FROM turns WHERE id=? AND session_id=?',(turn_id,session)).fetchone()
        if row is None or not row['plan']: raise AppError('That answer has no table to show again.')
        return parse_plan(row['plan'])

    def rename(self,owner,session,title):
        title=(title or '').strip()[:100]
        if not title: raise AppError('Enter a title.')
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('UPDATE sessions SET title=? WHERE id=?',(title,session))

    def delete(self,owner,session):
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('DELETE FROM turns WHERE session_id=?',(session,))
            connection.execute('DELETE FROM sessions WHERE id=?',(session,))

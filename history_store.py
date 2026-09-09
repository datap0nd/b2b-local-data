"""Persistent local SQLite store: per-person conversations with every model reply, saved answers, and the access log.

Schema version 3 adds the results table: a compressed, bounded copy of each answer (its tables, chart specification,
presentation metadata, and the Summary/Detailed variants) linked to the turn that produced it, together with the plan,
the dataset fingerprint, and the verified freshness of the snapshot used. Raw source extracts are never stored. Before
the schema is migrated, a copy of the previous database file is written next to it (history.sqlite3.v2-backup-<stamp>);
restoring that copy together with the previous release is the documented rollback."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import zlib

from app_config import AppError
from query_engine import CALCULATION_VERSION, LINE_AMOUNT_FIELDS, parse_plan, typed_value

SCHEMA_VERSION=3
MAX_RESULT_BYTES=6_000_000   # compressed payload bound per saved answer
PREVIEW_ROWS=1000
CSV_NUMBER=re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')


class SavedResultTooLarge(AppError):
    """The compressed evidence exceeded the explicit per-answer storage bound."""


def ordered_supporting_rows(table,sort=None,direction='asc'):
    """Sort frozen serialized business values exactly, with stable identifier ties."""
    if direction not in ('asc','desc'):
        raise AppError('Choose ascending or descending order.')
    if sort is not None and sort not in table.get('columns',[]):
        raise AppError('That supporting-data sort column is not available.')
    if sort in LINE_AMOUNT_FIELDS and (((table.get('metadata') or {}).get('evidence') or {}).get('amount_complete') is False):
        raise AppError('Some supporting amounts are incomplete or have conflicting currencies. Choose another sort column to review those rows.')
    keys=['opportunity_no']+(['product_code'] if table.get('grain')=='opportunity_sku' else [])
    rows=sorted(table.get('rows') or [],key=lambda row:tuple(str(row.get(key) or '') for key in keys))
    if sort is None:
        return rows
    nonnull=[row for row in rows if row.get(sort) is not None]
    nulls=[row for row in rows if row.get(sort) is None]
    # typed_value uses Decimal for numeric business fields and keeps IDs as text.
    nonnull.sort(key=lambda row:typed_value(sort,row[sort]),reverse=direction=='desc')
    return nonnull+nulls


def supporting_csv(table,rows):
    """Same BOM, CRLF, quote-all and formula guard as frontend csvText; no floats."""
    def cell(value,kind='text'):
        text='' if value is None else ('true' if value else 'false') if isinstance(value,bool) else str(value)
        numeric=kind=='number' and CSV_NUMBER.fullmatch(text) is not None
        if not numeric and re.match(r'^\s*[=+\-@\t\r]',text):
            text="'"+text
        return '"'+text.replace('"','""')+'"'
    kinds=table.get('column_types') or {}
    lines=[','.join(cell(column) for column in table['columns'])]
    lines.extend(','.join(cell(row.get(column),kinds.get(column,'text')) for column in table['columns']) for row in rows)
    return '\ufeff'+'\r\n'.join(lines)


class HistoryStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.backup=None
        with self.connect() as connection:
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version>SCHEMA_VERSION:
                raise AppError('History schema is newer than this application. Use a compatible release.')
        if 0<version<SCHEMA_VERSION and self.path.exists():
            # Versioned migration: keep a restorable copy of the pre-upgrade database first.
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            self.backup=self.path.with_name(f'{self.path.name}.v{version}-backup-{stamp}')
            shutil.copy2(self.path,self.backup)
        with self.connect() as connection:
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
                CREATE TABLE IF NOT EXISTS results (
                    turn_id INTEGER PRIMARY KEY REFERENCES turns(id), session_id TEXT NOT NULL REFERENCES sessions(id), owner TEXT NOT NULL,
                    kind TEXT NOT NULL, plan TEXT, fingerprint TEXT, freshness TEXT, presentation TEXT, payload BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE INDEX IF NOT EXISTS results_session ON results(session_id);
            ''')
            columns={row[1] for row in connection.execute('PRAGMA table_info(turns)')}
            if 'model_reply' not in columns:
                # Version 1 databases gain the raw model reply column; existing turns keep it empty.
                connection.execute('ALTER TABLE turns ADD COLUMN model_reply TEXT')
            if 'kind' not in columns:
                # Version 3: each turn records whether it answered with data, a clarification, or a greeting.
                connection.execute("ALTER TABLE turns ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
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

    def list(self,owner,search=None):
        with self.connect() as connection:
            if search:
                pattern='%'+search.strip()[:100]+'%'
                return [dict(row) for row in connection.execute('SELECT id,title,updated_at,created_at FROM sessions WHERE owner=? AND (title LIKE ? OR id IN (SELECT session_id FROM turns WHERE question LIKE ?)) ORDER BY updated_at DESC,id LIMIT 200',(owner,pattern,pattern))]
            return [dict(row) for row in connection.execute('SELECT id,title,updated_at,created_at FROM sessions WHERE owner=? ORDER BY updated_at DESC,id LIMIT 200',(owner,))]

    def read(self,owner,session):
        with self.connect() as connection:
            info=self._owned(connection,owner,session)
            turns=[dict(row) for row in connection.execute('SELECT id,question,response,plan,model_reply,kind,created_at FROM (SELECT * FROM turns WHERE session_id=? ORDER BY id DESC LIMIT 200) ORDER BY id',(session,))]
            saved={row['turn_id']:row for row in connection.execute('SELECT turn_id,kind,fingerprint,freshness,presentation,created_at FROM results WHERE session_id=?',(session,))}
        for row in turns:
            row['plan']=json.loads(row['plan']) if row['plan'] else None
            row['model_reply']=json.loads(row['model_reply']) if row['model_reply'] else None
            result=saved.get(row['id'])
            row['has_result']=result is not None
            row['freshness']=json.loads(result['freshness']) if result and result['freshness'] else None
            row['kind']=row.get('kind') or ('data' if row['plan'] else 'clarify')
        return {'id':session,'title':info['title'],'created_at':info['created_at'],'updated_at':info['updated_at'],'turns':turns,'active_plan':json.loads(info['active_plan']) if info['active_plan'] else None}

    def context(self,owner,session):
        saved=self.read(owner,session)
        history=[]
        # The model sees each earlier answer together with the plan that produced it, so follow-ups refine real context.
        for turn in saved['turns'][-8:]:
            response=turn['response']
            if turn.get('plan'):
                result=self.load_result(owner,session,turn['id'])
                version=((result or {}).get('table',{}).get('metadata') or {}).get('calculation_version')
                if version!=CALCULATION_VERSION:
                    response='This data answer used earlier or unavailable calculations. Its previous amounts and summary values must not be reused. Keep the user question and filters as context; ask for a current rerun before referring to its old total.'
            answer=response+(('\nPlan: '+json.dumps(turn['plan'],separators=(',',':'))) if turn.get('plan') else '')
            history.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':answer}])
        return history,parse_plan(saved['active_plan']) if saved['active_plan'] else None

    def append(self,owner,session,question,response,plan=None,model_reply=None,kind=None):
        """Record one turn; returns its id so a saved answer can be attached."""
        encoded=plan.model_dump_json() if plan else None
        reply=json.dumps(model_reply,ensure_ascii=False) if model_reply is not None else None
        kind=kind or ('data' if plan else 'clarify')
        with self.connect() as connection:
            self._owned(connection,owner,session)
            cursor=connection.execute('INSERT INTO turns(session_id,question,response,plan,model_reply,kind) VALUES (?,?,?,?,?,?)',(session,question,response,encoded,reply,kind))
            connection.execute("UPDATE sessions SET active_plan=COALESCE(?,active_plan),title=CASE WHEN title='New conversation' THEN ? ELSE title END,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(encoded,question[:100],session))
            return cursor.lastrowid

    def turn_plan(self,owner,session,turn_id):
        with self.connect() as connection:
            self._owned(connection,owner,session)
            row=connection.execute('SELECT plan FROM turns WHERE id=? AND session_id=?',(turn_id,session)).fetchone()
        if row is None or not row['plan']: raise AppError('That answer has no table to show again.')
        return parse_plan(row['plan'])

    def turn(self,owner,session,turn_id):
        with self.connect() as connection:
            self._owned(connection,owner,session)
            row=connection.execute('SELECT id,question,response,plan,kind,created_at FROM turns WHERE id=? AND session_id=?',(turn_id,session)).fetchone()
        if row is None: raise AppError('That answer does not exist in this conversation.')
        turn=dict(row); turn['plan']=json.loads(turn['plan']) if turn['plan'] else None
        return turn

    # ----- saved answers -----
    @staticmethod
    def bounded(payload):
        """Keep row previews and complete aggregate groups; save_result bounds bytes."""
        table=dict(payload)
        rows=list(table.get('rows') or [])
        table['rows']=rows if table.get('result_kind')=='aggregate' else rows[:PREVIEW_ROWS]
        if len(table['rows'])<len(rows): table['truncated']=True
        return table

    def save_result(self,owner,session,turn_id,kind,plan,fingerprint,freshness,payload):
        """Persist a compressed, bounded answer (primary table, variants, answer text) with its provenance."""
        body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        blob=zlib.compress(body,6)
        if len(blob)>MAX_RESULT_BYTES: raise SavedResultTooLarge('The answer is too large to save with the conversation.')
        with self.connect() as connection:
            self._owned(connection,owner,session)
            if connection.execute('SELECT 1 FROM turns WHERE id=? AND session_id=?',(turn_id,session)).fetchone() is None: raise AppError('That answer does not exist in this conversation.')
            connection.execute('INSERT OR REPLACE INTO results(turn_id,session_id,owner,kind,plan,fingerprint,freshness,presentation,payload) VALUES (?,?,?,?,?,?,?,?,?)',
                               (turn_id,session,owner,kind,plan.model_dump_json() if plan else None,fingerprint,json.dumps(freshness) if freshness is not None else None,(payload.get('table') or {}).get('presentation'),blob))

    def load_result(self,owner,session,turn_id):
        """The saved answer of an owned turn, decompressed; None when the turn predates saved answers."""
        with self.connect() as connection:
            self._owned(connection,owner,session)
            row=connection.execute('SELECT kind,plan,fingerprint,freshness,payload,created_at FROM results WHERE turn_id=? AND session_id=? AND owner=?',(turn_id,session,owner)).fetchone()
        if row is None: return None
        payload=json.loads(zlib.decompress(row['payload']).decode('utf-8'))
        return {'kind':row['kind'],'plan':json.loads(row['plan']) if row['plan'] else None,'fingerprint':row['fingerprint'],'freshness':json.loads(row['freshness']) if row['freshness'] else None,'saved_at':row['created_at'],**payload}

    def load_supporting(self,owner,session,turn_id,view='summary'):
        """Read only this owner's frozen evidence; never query a current snapshot."""
        if view not in ('summary','detail'):
            raise AppError('Choose summary or detail supporting data.')
        saved=self.load_result(owner,session,turn_id)
        if saved is None:
            self.turn(owner,session,turn_id)
            return {'available':False,'can_rerun':True,'message':'Supporting data was not retained for this answer. Run with current data to create a new answer and supporting list.'}
        if ((saved.get('table') or {}).get('metadata') or {}).get('calculation_version')!=CALCULATION_VERSION:
            return {'available':False,'can_rerun':True,'message':'This answer used earlier calculations. Run with current data to create corrected supporting data.'}
        supporting=saved.get('supporting')
        if not supporting:
            return {'available':False,'can_rerun':True,'message':'This saved answer predates supporting lists. Run with current data to create one.'}
        if not supporting.get('available'):
            return {key:value for key,value in supporting.items() if key!='views'}
        table=(supporting.get('views') or {}).get(view)
        if not table or len(table.get('rows') or [])!=table.get('total_rows'):
            return {'available':False,'can_rerun':True,'message':'The complete supporting list is not retained for this answer. Run with current data to create a new one.'}
        return {'available':True,'view':view,'table':table}

    def rename(self,owner,session,title):
        title=(title or '').strip()[:100]
        if not title: raise AppError('Enter a title.')
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('UPDATE sessions SET title=? WHERE id=?',(title,session))

    def delete(self,owner,session):
        with self.connect() as connection:
            self._owned(connection,owner,session)
            connection.execute('DELETE FROM results WHERE session_id=?',(session,))
            connection.execute('DELETE FROM turns WHERE session_id=?',(session,))
            connection.execute('DELETE FROM sessions WHERE id=?',(session,))

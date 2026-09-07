"""Rebuild coverage: bootstrap and capability gating, saved answers with deterministic view actions and dated reruns,
history migration with a restorable backup, the verified data-update time adapter, Summary/Detailed conservation
against the reference evaluator, per-currency metadata, and the deterministic answer text."""
from decimal import Decimal
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pandas as pd
from answer_text import compose_answer, default_suggestions, display
from app_config import Settings
from data_layer import RAW_COLUMNS, build_canonical_views, demo_rows, freshness_of
from history_store import SCHEMA_VERSION, HistoryStore
from query_engine import QueryExecutor, parse_plan
from reference_evaluator import ReferenceSource, evaluate_view

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_fixture import synthetic_records
from test_api import LocalServer


def demo_server(home, flag, name='Test Person'):
    views = build_canonical_views(demo_rows()); views.source, views.source_name = 'demo', 'fictional demo data'
    repository = MagicMock(); repository.load.return_value = views
    planner = MagicMock(); planner.plan.return_value = parse_plan({})
    return LocalServer(Settings(Path(home), {'DB_KIND': 'demo', 'B2B_ENABLE_ACCEPTANCE_UI': flag}), repository=repository, planner=planner, name=name)


class BootstrapAndGatingTests(unittest.TestCase):
    def test_bootstrap_is_public_and_lists_capabilities_without_model_or_source_details(self):
        with tempfile.TemporaryDirectory() as home:
            local = demo_server(home, 'false', name=None)
            try:
                boot = local.request('/api/bootstrap')
                self.assertTrue(boot['identity']['login_required']); self.assertEqual(boot['identity']['mode'], 'name')
                self.assertEqual(boot['capabilities'], {'acceptance_ui': False, 'samples': True, 'saved_results': True, 'contract_version': 2, 'views': ['summary', 'detail'], 'presentations': ['table', 'chart', 'cards']})
                self.assertEqual(set(boot), {'identity', 'capabilities'}); self.assertNotIn('model', json.dumps(boot)); self.assertNotIn('app_version', json.dumps(boot))
                local.login('Test Person')
                self.assertFalse(local.request('/api/bootstrap')['identity']['login_required'])
            finally: local.stop()

    def test_acceptance_routes_exist_only_behind_the_development_flag(self):
        with tempfile.TemporaryDirectory() as home:
            local = demo_server(home, 'false')
            try:
                with self.assertRaises(HTTPError) as caught: local.request('/api/test/suite')
                self.assertEqual(caught.exception.code, 404)
                with self.assertRaises(HTTPError) as caught: local.request('/api/test/runs', {})
                self.assertEqual(caught.exception.code, 404)
                with self.assertRaises(HTTPError) as caught: local.request('/api/refresh', {})
                self.assertIn(caught.exception.code, (404, 405))
            finally: local.stop()
        with tempfile.TemporaryDirectory() as home:
            local = demo_server(home, 'true')
            try:
                suite = local.request('/api/test/suite')
                self.assertTrue(local.request('/api/bootstrap')['capabilities']['acceptance_ui']); self.assertGreater(len(suite['steps']), 60)
            finally: local.stop()


class SavedAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.local = demo_server(cls.temp.name, 'false')
    @classmethod
    def tearDownClass(cls): cls.local.stop(); cls.temp.cleanup()

    def test_saved_answer_restores_without_recomputation_and_switches_views_deterministically(self):
        first = self.local.request('/api/sample', {'view': 'summary'})
        session, turn = first['session_id'], first['turn_id']
        saved = self.local.request(f'/api/sessions/{session}/turns/{turn}/result')
        self.assertTrue(saved['available']); self.assertEqual(saved['table']['result_digest'], first['table']['result_digest'])
        self.assertEqual(saved['table']['metadata']['version'], 2); self.assertEqual(saved['answer']['title'], 'Opportunities')
        self.assertEqual(len(saved['suggestions']), 3); self.assertEqual(list(saved['variants']), ['detail'])
        self.assertEqual(saved['table']['views']['scope_label'], None)
        detail = self.local.request(f'/api/sessions/{session}/turns/{turn}/actions', {'action': 'view', 'view': 'detail'})
        self.assertEqual(detail['table']['grain'], 'opportunity_sku'); self.assertIsNone(detail['table']['views']['scope_label'])   # no product filter: no scope caveat
        self.assertEqual(detail['answer']['title'], 'Opportunity products')
        # Row answers cannot become charts; the refusal is a plain error, not a model call.
        with self.assertRaises(HTTPError) as caught: self.local.request(f'/api/sessions/{session}/turns/{turn}/actions', {'action': 'presentation', 'presentation': 'chart'})
        self.assertEqual(caught.exception.code, 400)
        turns = self.local.request(f'/api/sessions/{session}')['turns']
        self.assertTrue(all(t['has_result'] for t in turns)); self.assertEqual(turns[0]['kind'], 'data')

    def test_run_with_current_data_creates_a_new_dated_turn_and_keeps_the_original(self):
        first = self.local.request('/api/sample', {'view': 'summary'})
        session, turn = first['session_id'], first['turn_id']
        rerun = self.local.request(f'/api/sessions/{session}/turns/{turn}/run', {})
        self.assertNotEqual(rerun['turn_id'], turn); self.assertEqual(rerun['rerun_of'], turn)
        self.assertEqual(rerun['table']['result_digest'], first['table']['result_digest'])
        turns = self.local.request(f'/api/sessions/{session}')['turns']
        self.assertEqual([t['id'] for t in turns], [turn, rerun['turn_id']])
        original = self.local.request(f'/api/sessions/{session}/turns/{turn}/result')
        self.assertEqual(original['table']['result_digest'], first['table']['result_digest'])
        self.assertIn('"rerun"', json.dumps(self.local.request('/api/access-log')))

    def test_pre_upgrade_turn_offers_a_rerun_instead_of_a_recomputed_answer(self):
        first = self.local.request('/api/sample', {'view': 'summary'})
        session = first['session_id']
        store = self.local.app.state.store
        owner = 'name:Test Person'
        turn_id = store.append(owner, session, 'older question', 'older answer', plan=parse_plan({'result_kind': 'rows', 'grain': 'opportunity'}), kind='data')
        older = self.local.request(f'/api/sessions/{session}/turns/{turn_id}/result')
        self.assertFalse(older['available']); self.assertTrue(older['can_rerun']); self.assertIn('Run with current data', older['message'])
        rerun = self.local.request(f'/api/sessions/{session}/turns/{turn_id}/run', {})
        self.assertEqual(rerun['rerun_of'], turn_id); self.assertEqual(rerun['table']['total_rows'], 3)


class HistoryMigrationTests(unittest.TestCase):
    def test_version_two_database_is_backed_up_before_migration_and_the_backup_restores(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / 'data' / 'history.sqlite3'; path.parent.mkdir()
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.executescript('''
                    CREATE TABLE sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'New conversation', active_plan TEXT,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                    CREATE TABLE turns (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), question TEXT NOT NULL, response TEXT NOT NULL, plan TEXT,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), model_reply TEXT);
                    INSERT INTO sessions(id, owner) VALUES ('s1', 'name:Ann');
                    INSERT INTO turns(session_id, question, response) VALUES ('s1', 'old question', 'old answer');
                    PRAGMA user_version=2;''')
            store = HistoryStore(path)
            self.assertIsNotNone(store.backup); self.assertTrue(store.backup.name.startswith('history.sqlite3.v2-backup-'))
            with closing(sqlite3.connect(path)) as connection, connection:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
                self.assertIn('results', {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})
                self.assertIn('kind', {r[1] for r in connection.execute('PRAGMA table_info(turns)')})
            turns = store.read('name:Ann', 's1')['turns']
            self.assertEqual(turns[0]['question'], 'old question'); self.assertFalse(turns[0]['has_result'])
            with closing(sqlite3.connect(store.backup)) as connection, connection:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
                self.assertNotIn('results', {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            # Rollback path: an older release reads the backup copy unchanged; reopening it here migrates again from a fresh backup.
            self.assertIsNone(HistoryStore(path).backup)


class Result:
    def __init__(self, scalar=None, row=None): self._scalar = scalar; self._row = row
    def scalar(self): return self._scalar
    def fetchone(self): return self._row


class FakeConnection:
    def __init__(self, setting='on', row=(10, 1, 10, '2026-09-07 17:20:00'), view_value=None, fail=None):
        self.setting, self.row, self.view_value, self.fail, self.statements = setting, row, view_value, fail, []
    def execute(self, clause):
        sql = str(clause); self.statements.append(sql)
        if self.fail and self.fail in sql: raise RuntimeError('connection reset')
        if 'track_commit_timestamp' in sql: return Result(scalar=self.setting)
        if 'pg_xact_commit_timestamp' in sql: return Result(row=self.row)
        return Result(scalar=self.view_value)


class FreshnessAdapterTests(unittest.TestCase):
    def settings(self, **values):
        return Settings(Path(tempfile.gettempdir()), {'DB_KIND': 'postgres', 'PGURL': 'db.example:5432/postgres'} | values)

    def test_commit_timestamp_of_one_atomic_load_is_verified(self):
        connection = FakeConnection()
        result = freshness_of(connection, 'bi_reporting.b2b_project', self.settings(), lambda r: r)
        self.assertEqual(result, {'status': 'verified', 'updated_at': '2026-09-07T17:20:00+00:00', 'timezone': 'UTC', 'method': 'commit_timestamp', 'reason': None})
        self.assertTrue(any('FROM bi_reporting.b2b_project' in s for s in connection.statements))

    def test_unverifiable_conditions_report_why_instead_of_substituting_a_load_time(self):
        cases = [(FakeConnection(setting='off'), 'track_commit_timestamp'), (FakeConnection(row=(10, 3, 10, '2026-09-07 17:20:00')), '3 transactions'),
                 (FakeConnection(row=(10, 1, 4, '2026-09-07 17:20:00')), 'no longer available'), (FakeConnection(row=(0, 0, 0, None)), 'empty'),
                 (FakeConnection(fail='pg_xact'), 'could not be read')]
        for connection, phrase in cases:
            result = freshness_of(connection, 'bi_reporting.b2b_project', self.settings(), lambda r: r)
            self.assertEqual(result['status'], 'unavailable'); self.assertIsNone(result['updated_at']); self.assertIn(phrase, result['reason'])

    def test_administrator_freshness_view_is_the_durable_fallback(self):
        connection = FakeConnection(view_value='2026-09-07 19:20:00+02')
        result = freshness_of(connection, 'bi_reporting.b2b_project', self.settings(B2B_FRESHNESS_VIEW='bi_reporting.b2b_freshness', B2B_FRESHNESS_COLUMN='loaded_at'), lambda r: r)
        self.assertEqual(result['method'], 'freshness_view'); self.assertEqual(result['updated_at'], '2026-09-07 19:20:00+02')
        self.assertIn('max("loaded_at")', connection.statements[0].replace('"', '"')); self.assertNotIn('pg_xact', ' '.join(connection.statements))
        empty = freshness_of(FakeConnection(view_value=None), 'x.y', self.settings(B2B_FRESHNESS_VIEW='a.b'), lambda r: r)
        self.assertEqual(empty['status'], 'unavailable'); self.assertIn('no completed load time', empty['reason'])
        bad = freshness_of(FakeConnection(), 'x.y', self.settings(B2B_FRESHNESS_VIEW='drop table; --'), lambda r: r)
        self.assertIn('schema.view', bad['reason'])


def views_of(records):
    views = build_canonical_views(pd.DataFrame(records, columns=RAW_COLUMNS, dtype=object)); views.source, views.source_name = 'test', 'synthetic'
    return views


class ViewConservationAndCurrencyTests(unittest.TestCase):
    def test_summary_of_a_product_filtered_detail_result_matches_the_reference_evaluator(self):
        records = synthetic_records(); views = views_of(records); source = ReferenceSource(records)
        plan = parse_plan({'result_kind': 'rows', 'grain': 'opportunity_sku', 'filters': [{'field': 'product_code', 'operator': 'eq', 'value': 'P-500'}]})
        detail = QueryExecutor().execute(views, plan)
        summary = QueryExecutor().variant(views, plan, 'summary')
        self.assertEqual(summary['views']['scope_label'], 'Matching products only'); self.assertEqual(summary['grain'], 'opportunity')
        expected = evaluate_view(source, {'intent': 'table', 'grain': 'sku', 'filters': [{'field': 'product_code', 'op': 'eq', 'value': 'P-500'}], 'columns': []}, 'summary')
        self.assertEqual({r['opportunity_no'] for r in summary['rows']}, {r['opportunity_no'] for r in expected['rows']})
        self.assertEqual(sum(Decimal(str(r['opportunity_amount'])) for r in summary['rows']), sum(Decimal(str(r['sku_amount'])) for r in detail['rows']))
        self.assertEqual(sum(Decimal(str(r['opportunity_amount'])) for r in summary['rows']), Decimal(str(expected['totals']['amount'])))
        self.assertEqual(sum(Decimal(str(r['quantity'])) for r in summary['rows']), Decimal(str(expected['totals']['quantity'])))
        self.assertTrue(all(r['product_codes'] == 'P-500' for r in summary['rows']))

    def test_currency_metadata_and_answer_text_never_combine_mixed_currencies(self):
        records = synthetic_records()
        for record in records:
            if record['opportunity_no'] == 'OPP-0002': record['amount_converted_currency'] = record['opp_amount_converted_currency'] = 'USD'
        views = views_of(records)
        table = QueryExecutor().execute(views, parse_plan({'result_kind': 'rows', 'grain': 'opportunity'}))
        currency = table['metadata']['currency']
        self.assertTrue(currency['mixed']); self.assertIsNone(currency['code']); self.assertEqual(set(currency['codes']), {'EUR', 'USD'})
        by_currency = table['metadata']['complete']['by_currency']
        self.assertEqual(set(by_currency), {'EUR', 'USD'}); self.assertEqual(by_currency['USD']['opportunities'], 1)
        answer = compose_answer(table)
        self.assertEqual(answer['metrics'], [])
        self.assertEqual(answer['sentence'], '')
        self.assertTrue(all(v['amount'] is not None for v in by_currency.values()))
        single = QueryExecutor().execute(views, parse_plan({'result_kind': 'rows', 'grain': 'opportunity', 'filters': [{'field': 'opportunity_owner', 'operator': 'eq', 'value': 'Ann Ahl'}]}))
        self.assertEqual(single['metadata']['currency']['code'], 'EUR')
        self.assertEqual(compose_answer(single)['metrics'], [])
        self.assertEqual(set(single['metadata']['complete']['by_currency']), {'EUR'})

    def test_answer_text_uses_readable_group_labels_and_deterministic_suggestions(self):
        self.assertEqual(display('close_month', '2024-01-01'), 'Jan 2024'); self.assertEqual(display('close_date', '2026-02-02'), '2 Feb 2026'); self.assertEqual(display('stage', None), 'Unknown')
        views = views_of(synthetic_records(years=3))
        chart = QueryExecutor().execute(views, parse_plan({'result_kind': 'aggregate', 'presentation': 'chart', 'chart_type': 'line', 'group_by': ['close_month'], 'measures': ['amount']}))
        answer = compose_answer(chart)
        self.assertRegex(answer['sentence'], r'Largest amount: [A-Z][a-z]{2} \d{4} with')
        self.assertEqual(default_suggestions(chart), ['Show the same values by owner', 'Show the same values by opportunity status', 'Show those values as a table'])
        rows = QueryExecutor().execute(views, parse_plan({'result_kind': 'rows', 'grain': 'opportunity', 'filters': [{'field': 'stage', 'operator': 'eq', 'value': 'Won'}]}))
        self.assertEqual(default_suggestions(rows)[-1], 'Remove the stage restriction')
        total = QueryExecutor().execute(views, parse_plan({'result_kind': 'aggregate', 'presentation': 'cards', 'measures': ['amount']}))
        self.assertEqual(default_suggestions(total)[0], 'Break the total down by owner')


if __name__ == '__main__': unittest.main()

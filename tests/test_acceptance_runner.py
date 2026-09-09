"""End-to-end suite runs with a scripted model, plus failure injection, cancellation, idempotency, and qualification."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from acceptance_runner import AcceptanceRunner, md
from acceptance_suite import STEPS, manifest
from app_config import AppError, Settings
from data_layer import RAW_COLUMNS, DataRepository
from query_engine import QueryExecutor
from query_service import QueryService
from reference_evaluator import ReferenceSource

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_fixture import ScriptedPlanner, synthetic_records
from acceptance_suite import select_witnesses


class FrameRepository:
    def __init__(self, records): self.frame = pd.DataFrame(records, columns=RAW_COLUMNS, dtype=object); self.loads = 0
    def load_raw(self):
        self.loads += 1
        return self.frame.copy(), 'postgres', 'test.b2b_project'


def witnesses_for(records):
    return select_witnesses(ReferenceSource(records), records)[0]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.records = synthetic_records(); self.witnesses = witnesses_for(self.records)
        self.settings = Settings(self.home, {'DB_KIND': 'postgres', 'B2B_SOURCE_CONTRACT_VERIFIED':'true', 'PGURL': 'db.example:5432/postgres', 'RO_SQL_PW': 'top-secret-password', 'LLM_API_KEY': 'model-secret-key',
                                             'LLM_MODEL_NAME': 'qwen-test', 'LLM_API_URL': 'http://127.0.0.1:4002/v1/chat/completions'}, rules='- local rule')
        self.repository = FrameRepository(self.records)
    def tearDown(self): self.temp.cleanup()
    def runner(self, planner=None, **kwargs):
        planner = planner or ScriptedPlanner(self.witnesses, **kwargs)
        return AcceptanceRunner(self.settings, self.repository, QueryService(planner, QueryExecutor()), self.home / 'data'), planner
    def drive(self, runner, owner='alice', browser='pass', stop_after=None):
        status = runner.start(owner); run_id = status['run']['id']
        for index in range(len(STEPS)):
            if stop_after is not None and index >= stop_after: break
            runner.step(owner, run_id, index)
        if browser:
            for check in status['run']['browser']:
                runner.record_browser(owner, run_id, check['id'], browser, {'e': 1}, {'o': 1}, 'recorded by test')
        return run_id
    def test_scripted_model_passes_every_step_and_report_is_complete(self):
        runner, planner = self.runner()
        run_id = self.drive(runner)
        status = runner.status('alice', run_id)
        failing = [(s['id'], s['status'], s.get('interpretation'), s.get('error')) for s in status['run']['steps'] if s['status'] != 'pass']
        self.assertEqual(failing, [])
        self.assertTrue(status['complete']); self.assertTrue(status['full_pass']); self.assertEqual(status['run']['status'], 'complete')
        self.assertEqual(status['counts']['passed'], len(STEPS)); self.assertEqual(status['counts']['browser_passed'], 16)
        self.assertEqual(self.repository.loads, 1)                              # one frozen snapshot for the whole run
        self.assertTrue(status['run']['snapshot']['canonical_parity'])
        self.assertEqual(len(planner.calls), len(STEPS))   # every step asked once (Auto-mode variants reuse a prompt with another layout)
        report = runner.report('alice', run_id)
        for heading in ('## Run identity and source', '## Scorecard', '## Per-case evidence', '## Comparison with the previous run', '## Review instructions', '### T25', '### C6', 'Browser check 12'):
            self.assertIn(heading, report)
        for secret in ('top-secret-password', 'model-secret-key', 'Authorization'):
            self.assertNotIn(secret, report)
        self.assertIn('1st Channel', report); self.assertIn('fp1', report); self.assertIn(self.witnesses['product'], report)
        detail = runner.detail('alice', run_id, 'T23')
        self.assertEqual(detail['result']['total_rows'], 1); self.assertTrue(detail['data']['ok']); self.assertEqual(detail['result']['rows'][0]['product_code'], self.witnesses['dup_sku'])
        self.assertEqual(runner.detail('alice', run_id, 'T26')['result']['total_rows'], 0)
        self.assertEqual(runner.detail('alice', run_id, 'B4')['result']['rows'], runner.detail('alice', run_id, 'B3')['result']['rows'])
    def test_conversations_are_isolated_from_saved_history_and_each_other(self):
        runner, planner = self.runner()
        run_id = self.drive(runner, browser=None)
        sessions = {s['id']: s['session'] for s in json.loads((self.home / 'data/acceptance/runs' / (run_id + '.json')).read_text(encoding='utf-8'))['steps']}
        self.assertEqual(len({sessions[i] for i in ('A1', 'A2', 'A3', 'A4', 'A5', 'A6')}), 1)
        self.assertEqual(len({sessions[i] for i in ('T01', 'T02', 'T09', 'A1', 'B1', 'C1')}), 6)
        self.assertFalse((self.home / 'data/history.sqlite3').exists())
        self.assertEqual(runner.history.list('alice')[0]['title'][:5], 'Show ')
    def test_wrong_plans_fail_interpretation_and_data_separately(self):
        overrides = {'T09': {'filters': [{'field': 'stage', 'operator': 'eq', 'value': 'Lost'}]},                        # wrong filter
                     'T12': {'filters': [{'field': 'opportunity_owner', 'operator': 'contains', 'value': self.witnesses['owner_a']}]},  # same rows, wrong operator
                     'T27': {'intent': 'chart', 'chart_type': 'bar', 'dimensions': ['stage_group'], 'measures': ['amount']},          # missing measure
                     'T34': {'intent': 'metric', 'measures': ['amount']},                                                # executed instead of clarifying
                     'A2': {'context_action': 'refine', 'intent': 'clarify', 'clarification': 'Which owner?'}}          # unexpected clarification blocks A3..A6
        runner, _ = self.runner(overrides=overrides)
        run_id = self.drive(runner)
        steps = {s['id']: s for s in runner.status('alice', run_id)['run']['steps']}
        self.assertEqual(steps['T09']['status'], 'fail'); self.assertFalse(steps['T09']['interpretation']['ok']); self.assertFalse(steps['T09']['data_ok'])
        self.assertEqual(steps['T12']['status'], 'fail'); self.assertFalse(steps['T12']['interpretation']['ok']); self.assertTrue(steps['T12']['data_ok'])
        self.assertEqual(steps['T27']['status'], 'fail'); self.assertIn('measures', steps['T27']['interpretation']['problems'][0])
        self.assertEqual(steps['T34']['status'], 'fail'); self.assertFalse(steps['T34']['data_ok'])
        self.assertEqual(steps['A2']['status'], 'fail')
        for later in ('A3', 'A4', 'A5', 'A6'): self.assertEqual(steps[later]['status'], 'blocked')
        for unaffected in ('B1', 'C6', 'T10'): self.assertEqual(steps[unaffected]['status'], 'pass')
        status = runner.status('alice', run_id)
        self.assertTrue(status['complete']); self.assertFalse(status['full_pass'])
        self.assertIn('prevents qualification', runner.report('alice', run_id))
    def test_model_failure_marks_error_without_stopping_unrelated_cases(self):
        runner, _ = self.runner(fail_on=('T05', 'C2'))
        run_id = self.drive(runner)
        steps = {s['id']: s for s in runner.status('alice', run_id)['run']['steps']}
        self.assertEqual(steps['T05']['status'], 'error'); self.assertEqual(steps['T06']['status'], 'pass')
        self.assertEqual(steps['C2']['status'], 'error'); self.assertEqual(steps['C3']['status'], 'blocked'); self.assertEqual(steps['C1']['status'], 'pass')
    def test_data_failure_retains_context_and_explicit_reset_recovers(self):
        runner, _ = self.runner(fail_on=('E1',))
        from acceptance_runner import compare as original_compare
        def faulty_check(expected, table):
            result=original_compare(expected,table)
            if table.get('result_kind')=='aggregate':
                result['ok']=False
                result['checks']['seeded_arithmetic_error']=False
            return result
        with patch('acceptance_runner.compare',side_effect=faulty_check):
            run_id=self.drive(runner)
        steps={s['id']:s for s in runner.status('alice',run_id)['run']['steps']}
        self.assertEqual(steps['B2']['status'],'fail')
        self.assertNotEqual(steps['B3']['status'],'blocked')
        self.assertEqual(steps['B6']['status'],'pass')
        self.assertEqual(steps['E2']['status'],'blocked')
        self.assertEqual(steps['E4']['status'],'pass')
        self.assertFalse(runner.status('alice',run_id)['full_pass'])
    def test_steps_are_ordered_idempotent_and_serialized(self):
        runner, planner = self.runner()
        run_id = runner.start('alice')['run']['id']
        with self.assertRaises(AppError): runner.step('alice', run_id, 3)
        first = runner.step('alice', run_id, 0); again = runner.step('alice', run_id, 0)
        self.assertEqual(first['step'], again['step']); self.assertEqual(len(planner.calls), 1)
        with self.assertRaises(AppError): runner.step('bob', run_id, 1)
        with self.assertRaises(AppError): runner.start('alice')
        runner.service.lane.acquire()
        try:
            with self.assertRaises(AppError): runner.step('alice', run_id, 1)
        finally: runner.service.lane.release()
        with self.assertRaises(AppError): runner.record_browser('alice', run_id, 99, 'pass')
        with self.assertRaises(AppError): runner.record_browser('alice', run_id, 1, 'maybe')
    def test_cancel_and_interruption_produce_partial_reports(self):
        runner, _ = self.runner()
        run_id = self.drive(runner, browser=None, stop_after=5)
        status = runner.cancel('alice', run_id)
        self.assertEqual(status['run']['status'], 'cancelled'); self.assertEqual(status['counts']['blocked'], len(STEPS)-5); self.assertEqual(status['counts']['browser_blocked'], 16)
        with self.assertRaises(AppError): runner.step('alice', run_id, 5)
        report = runner.report('alice', run_id); self.assertIn('Cancelled by the user', report); self.assertIn('partial', report)
        runner2, _ = self.runner()
        run2 = self.drive(runner2, browser=None, stop_after=3)
        restarted = AcceptanceRunner(self.settings, self.repository, runner2.service, self.home / 'data')
        status = restarted.status('alice', run2)
        self.assertEqual(status['run']['status'], 'interrupted'); self.assertIn('restarted', restarted.report('alice', run2))
        self.assertTrue(restarted.start('alice')['run']['id'])
    def test_three_pass_qualification_and_reset(self):
        runner, _ = self.runner()
        for _ in range(2): self.drive(runner)
        self.assertEqual(runner.qualification('alice'), runner.qualification('alice') | {'ready': False, 'streak': 2})
        self.drive(runner)
        q = runner.qualification('alice'); self.assertTrue(q['ready']); self.assertEqual(q['streak'], 3)
        self.assertIn('Ready for review', runner.report('alice', runner.list_runs('alice')[0]['id']))
        self.assertFalse(runner.qualification('bob')['ready'])
        self.records.append(dict(self.records[0], comment='changed'))
        self.repository = FrameRepository(self.records); changed, _ = self.runner(ScriptedPlanner(witnesses_for(self.records)))
        self.drive(changed)
        q = changed.qualification('alice'); self.assertFalse(q['ready']); self.assertEqual(q['streak'], 1)
        comparison = changed.comparison('alice', changed.list_runs('alice')[0])
        self.assertIn('source_fingerprint', comparison['changes']); self.assertFalse(comparison['same_sequence'])
        with patch('acceptance_runner.today', return_value=date(2030, 1, 1)):
            self.drive(changed)
        self.assertEqual(changed.qualification('alice')['streak'], 1)
        failed = changed.start('alice', only_failed_from=changed.list_runs('alice')[0]['id'])
        self.assertIn('failed-only', failed['run']['scope']); self.assertTrue(all(s['status'] == 'not_applicable' for s in failed['run']['steps']))
        changed.cancel('alice', failed['run']['id'])
    def test_wrong_browser_observation_and_blocked_coverage_prevent_full_pass(self):
        runner, _ = self.runner()
        run_id = self.drive(runner, browser='fail')
        self.assertFalse(runner.status('alice', run_id)['full_pass'])
        small = FrameRepository(self.records[:12]); self.repository = small
        witnesses = witnesses_for(self.records[:12])
        runner, _ = self.runner(ScriptedPlanner(witnesses))
        run_id = self.drive(runner)
        status = runner.status('alice', run_id)
        self.assertGreater(status['counts']['blocked'], 0); self.assertFalse(status['full_pass']); self.assertTrue(status['complete'])
        self.assertIn('Blocked coverage', runner.report('alice', run_id))
    def test_markdown_escaping_and_manifest(self):
        self.assertEqual(md('a|b`c\nd'), 'a\\|b\\`c d')
        m = manifest(); self.assertEqual(len(m['steps']), len(STEPS)); self.assertEqual(len(m['browser_checks']), 16); self.assertEqual(m['suite_version'], '3.0.0')
        self.records[0]['end_customer'] = 'Pipe | Customer'; self.repository = FrameRepository(self.records)
        runner, _ = self.runner(ScriptedPlanner(witnesses_for(self.records)))
        run_id = self.drive(runner, browser=None, stop_after=2)
        self.assertIn('Pipe \\| Customer', runner.report('alice', run_id))

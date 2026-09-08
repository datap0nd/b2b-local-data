"""Live catalog contracts and evidence boundaries, separate from legacy qualification."""
from collections import Counter
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from app_config import AppError, Settings
from acceptance_runner import AcceptanceRunner, replace_evidence
from acceptance_suite import select_witnesses, match_plan, reference_spec
from live_scenarios import SCENARIOS, STEPS, TARGETS
from reference_evaluator import ReferenceSource, evaluate
from query_engine import parse_plan, QueryExecutor
from query_service import QueryService
from evidence import validate_png
from scripts.capture_viewer import Recordings
from acceptance_fixture import synthetic_records, authored_plan
from test_acceptance_runner import FrameRepository
from urllib.error import HTTPError
from urllib.request import Request


def png():
    def chunk(kind, body): return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff\xff')) + chunk(b'IEND', b'')


class LiveCatalogTests(unittest.TestCase):
    def test_run_report_retries_windows_lock_without_repeating_work(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(Path(directory), {'DB_KIND': 'demo'})
            runner = AcceptanceRunner(settings, None, None, Path(directory) / 'data', live=True)
            run = {'id': 'a' * 32, 'version': 'previous'}
            runner._save(run)
            original = Path.replace
            denied = PermissionError('Temporarily locked by another process')
            denied.winerror = 5
            attempts = []
            def locked_once(source, target):
                attempts.append((source, target))
                if len(attempts) == 1:
                    self.assertEqual(json.loads(target.read_text())['version'], 'previous')
                    raise denied
                return original(source, target)
            with patch.object(Path, 'replace', locked_once), patch('acceptance_runner.sleep') as wait:
                runner._save({**run, 'version': 'new'})
            self.assertEqual(len(attempts), 2)
            wait.assert_called_once_with(.05)
            self.assertEqual(json.loads(runner._path(run['id']).read_text())['version'], 'new')

    def test_persistent_lock_keeps_previous_report_and_temporary_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / 'run.json', Path(directory) / 'run.tmp'
            old.write_text('previous'); new.write_text('new')
            denied = PermissionError('Locked'); denied.winerror = 32
            with patch.object(Path, 'replace', side_effect=denied) as rename, patch('acceptance_runner.sleep') as wait:
                with self.assertRaises(PermissionError): replace_evidence(new, old)
            self.assertEqual(rename.call_count, 8); self.assertEqual(wait.call_count, 7)
            self.assertEqual(old.read_text(), 'previous'); self.assertEqual(new.read_text(), 'new')
            with patch.object(Path, 'replace', side_effect=FileNotFoundError) as rename:
                with self.assertRaises(FileNotFoundError): replace_evidence(new, old)
            self.assertEqual(rename.call_count, 1)

    def test_live_http_actions_supporting_and_artifacts_are_owner_scoped(self):
        from test_api import LocalServer
        from acceptance_fixture import ScriptedPlanner
        records = synthetic_records()
        witnesses = select_witnesses(ReferenceSource(records), records)[0]
        with tempfile.TemporaryDirectory() as directory:
            local = LocalServer(Settings(Path(directory), {'DB_KIND': 'demo'}), repository=FrameRepository(records), planner=ScriptedPlanner(witnesses))
            try:
                suite = local.request('/api/test/suite')
                self.assertEqual(suite['scenario_count'], 200)
                started = local.request('/api/test/runs', {}); run_id = started['run']['id']
                for index in range(5):
                    result = local.request(f'/api/test/runs/{run_id}/step', {'step': index})
                    self.assertEqual(result['step']['status'], 'pass')
                payload = result['payload']
                session, turn_id = payload['session_id'], payload['turn_id']
                base = f'/api/test/runs/{run_id}/sessions/{session}/turns/{turn_id}'
                supporting = local.request(base + '/supporting?page=1&page_size=50')
                self.assertEqual(supporting['total_rows'], 60)
                self.assertEqual(len(supporting['table']['rows']), 10)
                action = local.request(base + '/actions', {'action': 'presentation', 'presentation': 'cards'})
                self.assertEqual(action['table']['rows'], payload['table']['rows'])
                with self.assertRaises(HTTPError): local.request(f'/api/sessions/{session}/turns/{turn_id}/supporting')
                sid = started['run']['scenarios'][0]['id']
                request = Request(local.base + f'/api/test/runs/{run_id}/scenarios/{sid}/png', data=png(), headers={'Content-Type': 'image/png'})
                with local.opener.open(request) as response: self.assertEqual(response.status, 200)
                review = local.request(f'/api/test/runs/{run_id}/review?start=0&size=1')
                self.assertEqual(review['scenarios'][0]['png']['width'], 1)
                local.login('Different reviewer')
                with self.assertRaises(HTTPError): local.request(base + '/supporting')
                with self.assertRaises(HTTPError): local.request(f'/api/test/runs/{run_id}/payloads/T05')
            finally: local.stop()

    def test_full_live_run_retains_payloads_and_requires_200_images(self):
        from copy import deepcopy
        class Planner:
            current = None
            calls = 0
            def plan(self, question, history, previous=None, view='auto'):
                self.calls += 1
                authored = deepcopy(self.current)
                # The regression model supplies full authored plans. Natural
                # language ability is assessed only by the real live run.
                authored['expect']['filters'] = []
                plan = authored_plan(authored, witnesses)
                if self.current['id'].startswith('S'):
                    plan['context_action'] = 'replace'
                    plan['filters'] = []
                    for f in self.current['expect'].get('filters', []):
                        value, op = f['value'], f['op']
                        if isinstance(value, str) and value.startswith('{'): value = witnesses[value[1:-1]]
                        if op == 'year': value, op = [f'{value}-01-01', f'{value}-12-31'], 'between'
                        if op == 'group': op = 'eq'
                        plan['filters'].append({'field': f['field'], 'operator': op, 'value': value})
                else: plan = authored_plan(self.current, witnesses)
                return parse_plan(plan)
        records = synthetic_records()
        witnesses = select_witnesses(ReferenceSource(records), records)[0]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = Settings(home, {'DB_KIND': 'demo'})
            planner = Planner()
            runner = AcceptanceRunner(settings, FrameRepository(records), QueryService(planner, QueryExecutor()), home / 'data', live=True)
            state = runner.start('alice'); run_id = state['run']['id']
            for index, step in enumerate(STEPS):
                planner.current = step
                result = runner.step('alice', run_id, index)
                if result['step']['status'] == 'pass' and result.get('table'):
                    self.assertEqual(result['payload']['table']['result_digest'], result['table']['result_digest'])
                    self.assertIn('answer', result['payload'])
            self.assertFalse(runner.is_complete(runner._load('alice', run_id)))
            self.assertIsNone(runner.status('alice', run_id)['next_step'])
            for check in runner._load('alice', run_id)['browser']: runner.record_browser('alice', run_id, check['id'], 'pass', notes='Synthetic regression observation')
            for s in SCENARIOS:
                runner.record_scenario('alice', run_id, s['id'], {'status': 'pass', 'notes': 'Synthetic regression observation'})
                runner.save_evidence('alice', run_id, s['id'], png())
            finished = runner.status('alice', run_id)
            self.assertEqual(finished['run']['status'], 'complete')
            self.assertFalse(finished['full_pass'])  # Human visual review is pending.
            self.assertEqual(len(list((home / 'test-results' / run_id).glob('*.png'))), 200)
            runner.save_evidence('alice', run_id, SCENARIOS[0]['id'], png())
            self.assertEqual(len(list((home / 'test-results' / run_id).glob('*.png'))), 200)
            self.assertTrue((home / 'test-results' / run_id / 'manifest.json').is_file())
            with self.assertRaises(AppError): runner.payload('eve', run_id, STEPS[0]['id'])
            with self.assertRaises(AppError): runner.save_evidence('alice', run_id, '../escape', png())
            self.assertFalse((home / 'data/history.sqlite3').exists())
            # New scenarios must not accidentally fail their own arithmetic oracle.
            failures = [(s['id'], s.get('error'), s.get('interpretation'), s.get('data_ok')) for s in finished['run']['steps'] if s['id'].startswith('S') and s['status'] in ('fail', 'error')]
            self.assertEqual(failures, [])

    def test_exact_counts_and_isolation(self):
        self.assertEqual(len(SCENARIOS), 200)
        self.assertEqual(Counter(s['category'] for s in SCENARIOS), TARGETS)
        self.assertEqual(len({s['id'] for s in STEPS}), len(STEPS))
        self.assertEqual(len({s['conversation'] for s in STEPS}), 200)
        self.assertEqual(sum(len(s['steps']) > 1 for s in SCENARIOS if s['category'] == 'continuity'), 40)
        for scenario in SCENARIOS:
            self.assertEqual([t['turn_number'] for t in scenario['steps']], list(range(1, len(scenario['steps']) + 1)))
            self.assertTrue(all(t['view'] == 'auto' and t['expect'] and t['behavior'] for t in scenario['steps']))

    def test_all_new_expectations_are_executable_reference_contracts(self):
        source = ReferenceSource(synthetic_records())
        witnesses = select_witnesses(source, synthetic_records())[0]
        for step in STEPS:
            if not step['id'].startswith('S') or step['expect']['intent'] == 'clarify': continue
            with self.subTest(step=step['id']):
                # Literal authored filter values, including ISO dates and decimals,
                # are independent of the model and must be valid QueryPlan inputs.
                import copy
                authored = copy.deepcopy(step)
                authored['expect']['filters'] = []
                plan = authored_plan(authored, witnesses)
                plan['context_action'] = 'replace'
                plan['filters'] = []
                for f in step['expect']['filters']:
                    v = f['value']
                    if isinstance(v, str) and v.startswith('{'): v = witnesses[v[1:-1]]
                    op = f['op']
                    if op == 'year': v, op = [f'{v}-01-01', f'{v}-12-31'], 'between'
                    if op == 'group': op = 'eq'
                    plan['filters'].append({'field': f['field'], 'operator': op, 'value': v})
                parsed = parse_plan(plan)
                ok, problems, variant = match_plan({'plan': parsed.model_dump(mode='json'), 'kind': 'table'}, step, witnesses)
                self.assertTrue(ok, problems)
                result = evaluate(source, reference_spec(step, variant, witnesses))
                self.assertIn('rows', result)

    def test_png_validation_rejects_corruption_and_traversal(self):
        self.assertEqual(validate_png(png()), (1, 1))
        for body in [b'not png', png()[:-1], png() + b'extra', png()[:30] + b'x' + png()[31:]]:
            with self.assertRaises(AppError): validate_png(body)

    def test_capture_order_retry_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Recordings(directory)
            r = store.start({'device': 'UGREEN-25854', 'mime': 'video/webm'})['id']
            first = b'\x1aE\xdf\xa3first'
            store.chunk(r, 0, first); store.chunk(r, 0, first)
            with self.assertRaises(ValueError): store.chunk(r, 0, b'conflict')
            with self.assertRaises(ValueError): store.chunk(r, 2, b'out of order')
            with self.assertRaises(ValueError): store.folder('../escape')
            store.chunk(r, 1, b'second')
            restored = Recordings(directory)
            result = restored.finish(r)
            self.assertEqual(Path(result['path']).read_bytes(), first + b'second')
            self.assertEqual(restored.finish(r), result)
            self.assertEqual(len(list(Path(directory).glob('*/*.chunk'))), 2)
            with self.assertRaises(ValueError): restored.chunk(r, 2, b'late')


if __name__ == '__main__': unittest.main()

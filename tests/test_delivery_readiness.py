"""Regression checks for the reviewed failures and the delivery machinery.

Planning: oversized default projections, invalid grain fields, redundant columns, currency filters, filter removal,
table-to-metric transitions, ambiguous requests, unsupported suggestions. Machinery: one recorded correction attempt
(success, failure, single history turn, no expected-answer leakage), typed digests, canonical mismatch diagnostics,
failure propagation, complete status accounting, replay runs, and comparison of partial runs."""
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import pandas as pd
from acceptance_runner import IDENTITY_KEYS, REPORT_VERSION, AcceptanceRunner
from acceptance_suite import BROWSER_CHECKS, STEP_INDEX, STEPS, SUITE_VERSION, check_clarification, manifest
from app_config import AppError, Settings
from data_layer import RAW_COLUMNS, SQL_COLUMNS, build_canonical_views, clean_date, demo_rows, resolve_columns
from history_store import HistoryStore
from query_engine import DEFAULT_COLUMNS, PlanRejected, PlannerClient, QueryExecutor, merge_plan, normalize_plan, parse_plan, result_digest, supported_suggestions, validate_execution
from query_models import Grain
from query_service import QueryService
from reference_evaluator import DIGEST_VERSION, EVALUATOR_VERSION, ReferenceSource, cell_token, compare, compare_grains, digest_rows, evaluate, r_date

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_fixture import ScriptedPlanner, synthetic_records
from acceptance_suite import render_prompt, select_witnesses


def witnesses_for(records):
    return select_witnesses(ReferenceSource(records), records)[0]


class FrameRepository:
    def __init__(self, records): self.frame = pd.DataFrame(records, columns=RAW_COLUMNS, dtype=object); self.loads = 0
    def load_raw(self):
        self.loads += 1
        return self.frame.copy(), 'postgres', 'test.b2b_project'


class PlanningTests(unittest.TestCase):
    def setUp(self): self.views = build_canonical_views(demo_rows()); self.executor = QueryExecutor()
    def execute(self, plan): return self.executor.execute(self.views, plan)

    def test_listing_every_default_column_is_the_default_table(self):
        plan = normalize_plan(parse_plan({'grain': 'opportunity_sku', 'dimensions': list(DEFAULT_COLUMNS[Grain.OPPORTUNITY_SKU])}))
        self.assertEqual(plan.dimensions, [])
        self.assertEqual(self.execute(plan)['columns'], DEFAULT_COLUMNS[Grain.OPPORTUNITY_SKU])
        # The opportunity default has fourteen columns: listing them exceeds the ten-dimension limit and is rejected as a plan.
        with self.assertRaises(PlanRejected) as error: parse_plan({'dimensions': list(DEFAULT_COLUMNS[Grain.OPPORTUNITY])})
        self.assertIn('10', str(error.exception))
        merged = merge_plan(None, parse_plan({'grain': 'opportunity_sku', 'dimensions': list(reversed(DEFAULT_COLUMNS[Grain.OPPORTUNITY_SKU]))}))
        self.assertEqual(merged.dimensions, [])

    def test_redundant_key_columns_are_dropped_and_explicit_columns_stay_strict(self):
        plan = normalize_plan(parse_plan({'dimensions': ['opportunity_no', 'opportunity_owner', 'stage']}))
        self.assertEqual(plan.dimensions, ['opportunity_owner', 'stage'])
        self.assertEqual(self.execute(plan)['columns'], ['opportunity_no', 'opportunity_owner', 'stage'])
        detail = normalize_plan(parse_plan({'grain': 'opportunity_sku', 'dimensions': ['product_code', 'opportunity_no', 'pet_name']}))
        self.assertEqual(detail.dimensions, ['pet_name'])
        self.assertEqual(self.execute(detail)['columns'], ['opportunity_no', 'product_code', 'pet_name'])

    def test_invalid_grain_field_names_the_field_and_the_grain(self):
        with self.assertRaises(PlanRejected) as error: validate_execution(parse_plan({'dimensions': ['pet_name', 'opportunity_owner']}))
        text = str(error.exception)
        self.assertIn('pet_name', text); self.assertIn('opportunity grain', text); self.assertIn('opportunity_sku', text); self.assertNotIn('opportunity_owner is', text)
        with self.assertRaises(PlanRejected) as error: validate_execution(parse_plan({'dimensions': ['password']}))
        self.assertIn('unknown field password', str(error.exception))
        with self.assertRaises(PlanRejected): self.execute(parse_plan({'dimensions': ['pet_name']}))

    def test_currency_filter_is_honoured_even_when_every_record_shares_it(self):
        result = self.execute(parse_plan({'filters': [{'field': 'opp_amount_converted_currency', 'operator': 'eq', 'value': 'EUR'}]}))
        self.assertEqual(result['total_rows'], 3); self.assertEqual(result['filters'], [{'field': 'opp_amount_converted_currency', 'operator': 'eq', 'value': 'EUR'}])
        self.assertEqual(self.execute(parse_plan({'filters': [{'field': 'opp_amount_converted_currency', 'operator': 'eq', 'value': 'USD'}]}))['total_rows'], 0)
        total = self.execute(parse_plan({'intent': 'metric', 'measures': ['amount'], 'filters': [{'field': 'opp_amount_converted_currency', 'operator': 'eq', 'value': 'EUR'}]}))
        self.assertEqual(total['rows'], [{'amount': '3600'}])

    def test_filter_retention_replacement_and_removal(self):
        previous = parse_plan({'filters': [{'field': 'stage', 'operator': 'eq', 'value': 'Open'}, {'field': 'opportunity_owner', 'operator': 'eq', 'value': 'Alex'}]})
        replaced = merge_plan(previous, parse_plan({'context_action': 'refine', 'filters': [{'field': 'opportunity_owner', 'operator': 'eq', 'value': 'Blair'}]}))
        self.assertEqual([(f.field, f.value) for f in replaced.filters], [('stage', 'Open'), ('opportunity_owner', 'Blair')])
        removed = merge_plan(replaced, parse_plan({'context_action': 'refine', 'remove_filters': ['opportunity_owner']}))
        self.assertEqual([(f.field, f.value) for f in removed.filters], [('stage', 'Open')])
        with self.assertRaises(PlanRejected): merge_plan(previous, parse_plan({'context_action': 'refine', 'remove_filters': ['password']}))
        with self.assertRaises(PlanRejected): merge_plan(previous, parse_plan({'remove_filters': ['stage']}))
        with self.assertRaises(PlanRejected): merge_plan(None, parse_plan({'context_action': 'refine', 'filters': []}))

    def test_table_to_metric_transition_drops_columns_sort_and_limit(self):
        table = parse_plan({'dimensions': ['opportunity_owner', 'stage'], 'sort': [{'field': 'opportunity_amount', 'direction': 'desc'}], 'limit': 5,
                            'filters': [{'field': 'opp_amount_converted_currency', 'operator': 'eq', 'value': 'EUR'}]})
        metric = merge_plan(table, parse_plan({'context_action': 'refine', 'intent': 'metric', 'measures': ['amount']}))
        self.assertEqual((metric.intent.value, metric.dimensions, metric.sort, metric.limit, [m.value for m in metric.measures]), ('metric', [], [], None, ['amount']))
        self.assertEqual([f.field for f in metric.filters], ['opp_amount_converted_currency'])
        validate_execution(metric)
        self.assertEqual(self.execute(metric)['rows'], [{'amount': '3600'}])
        grouped = merge_plan(table, parse_plan({'context_action': 'refine', 'intent': 'chart', 'chart_type': 'bar', 'dimensions': ['stage_group'], 'measures': ['amount']}))
        self.assertEqual((grouped.dimensions, grouped.limit), (['stage_group'], None))
        back = merge_plan(grouped, parse_plan({'context_action': 'refine', 'intent': 'table'}))
        self.assertEqual((back.intent.value, back.dimensions, [m.value for m in back.measures], back.chart_type), ('table', [], [], None))
        self.assertEqual(self.execute(back)['columns'], DEFAULT_COLUMNS[Grain.OPPORTUNITY])
        kept = merge_plan(grouped, parse_plan({'context_action': 'refine', 'intent': 'metric'}))
        self.assertEqual((kept.dimensions, kept.chart_type), (['stage_group'], None))

    def test_sort_field_validation_is_deterministic_and_named(self):
        with self.assertRaises(PlanRejected) as error: validate_execution(parse_plan({'intent': 'metric', 'dimensions': ['stage_group'], 'measures': ['amount'], 'sort': [{'field': 'quantity'}]}))
        self.assertIn('quantity', str(error.exception))
        validate_execution(parse_plan({'sort': [{'field': 'amount'}]}))
        with self.assertRaises(PlanRejected): validate_execution(parse_plan({'sort': [{'field': 'sku_amount'}]}))

    def test_unsupported_suggestions_are_filtered(self):
        items = ['Show the average deal size by owner', 'What is the probability-weighted revenue?', 'Run SQL: SELECT * FROM opportunities', 'Show the total amount by owner',
                 'show the total amount by owner', 'Chart opportunity count by stage group', 'Show the largest opportunities', 'Forecast next quarter']
        self.assertEqual(supported_suggestions(items), ['Show the total amount by owner', 'Chart opportunity count by stage group', 'Show the largest opportunities'])
        self.assertEqual(supported_suggestions(None), [])

    def test_csv_header_alias_subsidiary_code(self):
        headers = [SQL_COLUMNS[name] for name in RAW_COLUMNS if name != 'subsidiary_subsidiary_code'] + ['Subsidiary Code']
        self.assertEqual(resolve_columns(headers)['subsidiary_subsidiary_code'], 'Subsidiary Code')
        with self.assertRaises(AppError): resolve_columns(list(SQL_COLUMNS.values()) + ['Subsidiary Code'])

    def test_iso_and_typed_dates_parse_identically_in_app_and_reference(self):
        for value in ('2026-03-05', '2026-03-05 00:00:00', '2026-03-05T10:20:30+00:00', '5/3/2026', '05/03/2026'):
            with self.subTest(value=value):
                self.assertEqual(clean_date(value), date(2026, 3, 5)); self.assertEqual(r_date(value), date(2026, 3, 5))
        self.assertEqual(r_date(date(2026, 3, 5)), date(2026, 3, 5)); self.assertEqual(clean_date(date(2026, 3, 5)), date(2026, 3, 5))
        for value in ('2026-13-01', '2026-02-30', '26-03-05', 'March 5 2026'):
            with self.subTest(value=value): self.assertIsNone(clean_date(value)); self.assertIsNone(r_date(value))
        rows = demo_rows(); rows[0]['close_date'] = '2026-10-15'; rows[1]['close_date'] = '2026-10-15 00:00:00'
        views = build_canonical_views(rows); reference = ReferenceSource(rows)
        self.assertTrue(compare(evaluate(reference, {'grain': 'opportunity', 'intent': 'table', 'columns': ['close_date']}), QueryExecutor().execute(views, parse_plan({'dimensions': ['close_date']})))['ok'])

    def test_planner_prompt_documents_defaults_transitions_and_currency(self):
        settings = Settings(Path('.'), {'LLM_MODEL_NAME': 'qwen-test', 'LLM_API_URL': 'http://127.0.0.1:4002/v1/chat/completions'}, rules='- rule one')
        client = PlannerClient(settings)
        prompt = client.system_prompt(None, 'auto', date(2026, 9, 7))
        for phrase in ('Default columns', 'mode only', 'mode include', 'never means the underlying rows', 'even if every record already uses that currency',
                       'Today: 2026-09-07', 'Never suggest averages', 'ambiguous between these two', 'do not carry over', 'presentation change alone', 'contract version 2'):
            self.assertIn(phrase, prompt)
        self.assertNotIn('4002', prompt)
        digest = client.prompt_digest(date(2026, 9, 7))
        self.assertTrue(digest.startswith('sha256:')); self.assertEqual(digest, client.prompt_digest(date(2026, 9, 7)))
        self.assertNotEqual(digest, PlannerClient(Settings(Path('.'), settings.values, rules='- rule two')).prompt_digest(date(2026, 9, 7)))
        self.assertNotEqual(digest, client.prompt_digest(date(2026, 9, 8)))


class CorrectionTests(unittest.TestCase):
    """One recorded correction attempt for invalid JSON, schema violations, and deterministic validation errors."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.records = synthetic_records(); self.witnesses = witnesses_for(self.records)
        self.views = build_canonical_views(pd.DataFrame(self.records, columns=RAW_COLUMNS, dtype=object))
        self.store = HistoryStore(self.home / 'history.sqlite3')
    def tearDown(self): self.temp.cleanup()
    def prompt(self, step_id): return render_prompt(STEPS[STEP_INDEX[step_id]], self.witnesses)
    def service(self, **kwargs):
        planner = ScriptedPlanner(self.witnesses, **kwargs)
        return QueryService(planner, QueryExecutor()), planner
    def ask(self, service, step_id, session=None):
        session = session or self.store.create('alice')
        return service.ask(self.store, 'alice', session, self.prompt(step_id), STEPS[STEP_INDEX[step_id]]['view'], self.views, '2026-09-07T00:00:00+00:00', effective_date=date(2026, 9, 7)), session

    def test_successful_repair_records_both_attempts_and_appends_one_turn(self):
        service, planner = self.service(rejections={'T01': ['{"intent":"dance","limit":"ten"}']})
        result, session = self.ask(service, 'T01')
        self.assertEqual(result['kind'], 'table'); self.assertEqual(result['table']['total_rows'], 60)
        attempts = result['diagnostics']['attempts']
        self.assertEqual([a['status'] for a in attempts], ['rejected', 'accepted']); self.assertTrue(result['diagnostics']['recovered'])
        self.assertIn('intent', attempts[0]['error']); self.assertFalse(attempts[0]['corrected']); self.assertTrue(attempts[1]['corrected'])
        self.assertEqual(result['diagnostics']['effective_date'], '2026-09-07'); self.assertEqual(planner.generations[0]['effective_date'], date(2026, 9, 7))
        self.assertEqual(len(self.store.read('alice', session)['turns']), 1)
        self.assertEqual(len(planner.corrections), 1)
        correction = planner.corrections[0]
        self.assertEqual(set(correction['correction']), {'rejected', 'feedback'})
        self.assertEqual(correction['correction']['rejected'], '{"intent":"dance","limit":"ten"}')
        self.assertEqual(correction['history'], planner.generations[0]['history']); self.assertEqual(correction['question'], self.prompt('T01'))

    def test_correction_carries_no_expected_answers(self):
        service, planner = self.service(rejections={'T05': ['{"intent":"metric"}']})   # schema-valid but no measure: deterministic validation error
        result, _ = self.ask(service, 'T05')
        self.assertTrue(result['diagnostics']['recovered'])
        feedback = planner.corrections[0]['correction']['feedback']
        self.assertIn('measure', feedback)
        forbidden = [str(self.views.opportunity['opportunity_amount'].dropna().map(Decimal).sum()), 'expected', 'reference', 'digest', 'total_rows'] + [str(v) for v in self.witnesses.values() if isinstance(v, str) and len(v) > 3]
        for word in forbidden:
            self.assertNotIn(word, feedback + json.dumps(planner.corrections[0]['history']))

    def test_second_invalid_reply_fails_without_touching_history(self):
        service, planner = self.service(rejections={'T01': ['{"intent":"dance"}', 'still not a plan {']})
        session = self.store.create('alice')
        with self.assertRaises(AppError) as error: self.ask(service, 'T01', session)
        self.assertIn('after one correction attempt', str(error.exception))
        self.assertEqual(len(planner.corrections), 1); self.assertEqual(self.store.read('alice', session)['turns'], [])

    def test_valid_but_wrong_answers_and_transport_failures_are_not_corrected(self):
        service, planner = self.service(overrides={'T09': {'filters': [{'field': 'stage', 'operator': 'eq', 'value': 'Lost'}]}}, fail_on=('T05',))
        result, _ = self.ask(service, 'T09')
        self.assertEqual(result['kind'], 'table'); self.assertEqual(len(result['diagnostics']['attempts']), 1); self.assertFalse(result['diagnostics']['recovered']); self.assertEqual(planner.corrections, [])
        with self.assertRaises(RuntimeError): self.ask(service, 'T05')
        self.assertEqual(planner.corrections, [])

    def test_plan_only_planners_cannot_be_corrected(self):
        class PlanOnly:
            def plan(self, question, history, previous=None, view='auto'): raise PlanRejected('Qwen returned an invalid QueryPlanV1.')
        with self.assertRaises(AppError) as error:
            QueryService(PlanOnly(), QueryExecutor()).ask(self.store, 'alice', self.store.create('alice'), 'Show deals', 'auto', self.views, 'now')
        self.assertNotIn('after one correction attempt', str(error.exception))

    def test_http_correction_request_repeats_the_conversation_plus_feedback_only(self):
        payloads, replies = [], iter(['{"intent":"dance"}', '{"intent":"table","filters":[{"field":"stage","operator":"eq","value":"Won"}]}'])
        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = json.dumps({'choices': [{'message': {'content': next(replies)}}]}).encode(); self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Stub); worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            settings = Settings(Path('.'), {'LLM_MODEL_NAME': 'qwen-test', 'LLM_API_URL': f'http://127.0.0.1:{server.server_address[1]}/v1/chat/completions', 'LLM_API_KEY': 'model-secret', 'B2B_LLM_STREAM': 'false'})
            service = QueryService(PlannerClient(settings), QueryExecutor())
            session = self.store.create('alice')
            self.store.append('alice', session, 'earlier question', 'earlier answer')
            result = service.ask(self.store, 'alice', session, 'Show the won deals', 'auto', self.views, 'now', effective_date=date(2026, 9, 7))
            self.assertEqual(result['plan']['filters'][0]['value'], 'Won'); self.assertTrue(result['diagnostics']['recovered'])
            first, second = payloads
            self.assertEqual(second['messages'][:len(first['messages'])], first['messages'])
            self.assertEqual([m['role'] for m in second['messages'][len(first['messages']):]], ['assistant', 'user'])
            self.assertEqual(second['messages'][-2]['content'], '{"intent":"dance"}')
            self.assertIn('rejected', second['messages'][-1]['content']); self.assertIn('intent', second['messages'][-1]['content'])
            self.assertNotIn('model-secret', json.dumps(second)); self.assertIn('Today: 2026-09-07', first['messages'][0]['content'])
            self.assertEqual(result['diagnostics']['settings']['stream'], False); self.assertEqual(result['diagnostics']['settings']['structured_output'], 'none')
            self.assertTrue(result['diagnostics']['settings']['correction_attempt']); self.assertEqual(result['diagnostics']['fallback_events'], [])
            self.assertEqual(len(self.store.read('alice', session)['turns']), 2)
        finally: server.shutdown(); server.server_close(); worker.join()


class EvaluatorTypingTests(unittest.TestCase):
    def test_typed_tokens_distinguish_identifiers_numbers_dates_and_nulls(self):
        self.assertEqual(cell_token('000123', 'text'), 's:000123'); self.assertEqual(cell_token('000123', 'number'), 'n:123'); self.assertEqual(cell_token(Decimal('750.00'), 'number'), 'n:750')
        self.assertEqual(cell_token(None, 'text'), 'null'); self.assertEqual(cell_token('null', 'text'), 's:null'); self.assertEqual(cell_token('', 'text'), 's:')
        self.assertEqual(cell_token(date(2026, 1, 2), 'date'), 'd:2026-01-02'); self.assertEqual(cell_token('2026-01-02', 'date'), 'd:2026-01-02'); self.assertEqual(cell_token('5/3/2026', 'date'), 'd:2026-03-05')
        self.assertEqual(cell_token(True, 'bool'), 'b:true'); self.assertEqual(cell_token('false', 'bool'), 'b:false'); self.assertEqual(cell_token('Zoë Ångström', 'text'), 's:Zoë Ångström')
        self.assertEqual(cell_token(Decimal('1E+3'), 'number'), 'n:1000'); self.assertEqual(cell_token('0.750', 'number'), 'n:0.75'); self.assertEqual(cell_token(7, 'text'), 's:7')
        text_rows = [{'opportunity_no': '007'}]; number_rows = [{'opportunity_no': '7'}]
        self.assertNotEqual(digest_rows(text_rows, ['opportunity_no']), digest_rows(number_rows, ['opportunity_no']))
        self.assertTrue(digest_rows(text_rows, ['opportunity_no']).startswith(DIGEST_VERSION + ':')); self.assertEqual(EVALUATOR_VERSION, 'reference-2')

    def test_production_and_reference_digests_agree_on_leading_zeros_unicode_decimals_and_nulls(self):
        rows = demo_rows()
        rows[0].update(opportunity_no='00042', end_customer='Zoë Ångström GmbH', amount_converted='10.50', opp_amount_converted='10.50', probability=None, close_date='')
        rows[1].update(opportunity_no='00042', amount_converted='0.005', opp_amount_converted='10.50', probability=None, close_date='')
        views = build_canonical_views(rows); reference = ReferenceSource(rows)
        for plan, spec in [({}, {'grain': 'opportunity', 'intent': 'table', 'columns': DEFAULT_COLUMNS[Grain.OPPORTUNITY][1:]}),
                           ({'intent': 'metric', 'dimensions': ['end_customer'], 'measures': ['amount', 'opportunity_count']}, {'grain': 'opportunity', 'intent': 'metric', 'group': ['end_customer'], 'measures': ['amount', 'opportunity_count']})]:
            with self.subTest(plan=plan):
                outcome = compare(evaluate(reference, spec), QueryExecutor().execute(views, parse_plan(plan)))
                self.assertTrue(outcome['ok'], outcome)
        self.assertEqual(reference.summary()['opportunity_digest'], result_digest(views.opportunity.to_dict('records'), list(views.opportunity.columns)))
        self.assertEqual(reference.summary()['sku_digest'], result_digest(views.sku.to_dict('records'), list(views.sku.columns)))
        self.assertEqual(views.opportunity.iloc[0]['opportunity_no'], '00042')

    def test_compare_reports_type_mismatches_and_preview_scope(self):
        views = build_canonical_views(demo_rows()); reference = ReferenceSource(demo_rows())
        expected = evaluate(reference, {'grain': 'opportunity', 'intent': 'table', 'columns': ['opportunity_amount']})
        actual = QueryExecutor().execute(views, parse_plan({'dimensions': ['opportunity_amount']}))
        outcome = compare(expected, actual); self.assertTrue(outcome['ok']); self.assertEqual(outcome['scope']['preview_cells'], 6); self.assertIn('digest', outcome['scope']['complete_verified_by'])
        wrong_type = dict(actual, column_types=dict(actual['column_types'], opportunity_amount='text'))
        self.assertFalse(compare(expected, wrong_type)['checks']['types'])
        stringly = dict(actual, rows=[dict(r, opportunity_no=r['opportunity_no'].lstrip('OPP-0')) for r in actual['rows']])
        self.assertEqual(compare(expected, stringly)['counts']['missing'], 3)

    def test_compare_grains_reports_keys_fields_types_and_raw_context(self):
        reference = ReferenceSource(demo_rows()); views = build_canonical_views(demo_rows())
        app = views.sku.to_dict('records')
        self.assertTrue(compare_grains(reference.sku, app, ['opportunity_no', 'product_code'], list(views.sku.columns), source=reference)['ok'])
        tampered = [dict(r) for r in app]
        tampered[0]['sku_amount'] = Decimal('999')
        tampered[0]['has_quality_warning'] = str(tampered[0]['has_quality_warning']).lower()   # the same flag as text is not a difference
        removed = tampered.pop(1); tampered.append(dict(removed, opportunity_no='OPP-404')); tampered.append(dict(tampered[0]))
        outcome = compare_grains(reference.sku, tampered, ['opportunity_no', 'product_code'], list(views.sku.columns), source=reference)
        self.assertFalse(outcome['ok'])
        counts = outcome['counts']
        self.assertEqual((counts['missing_keys'], counts['extra_keys'], counts['duplicate_keys'], counts['differing_rows']), (1, 1, 1, 1)); self.assertEqual(counts['by_column'], {'sku_amount': 1})
        cell = next(e for e in outcome['examples'] if e['kind'] == 'cell')
        self.assertEqual((cell['column'], cell['column_kind'], cell['reference']['type'], cell['app']['type']), ('sku_amount', 'number', 'Decimal', 'Decimal'))
        self.assertEqual(cell['app_token'], 'n:999'); self.assertTrue(cell['raw_rows']); self.assertEqual(cell['raw_rows'][0]['opportunity_no'], 'OPP-001')
        self.assertEqual({e['kind'] for e in outcome['examples']}, {'cell', 'missing_key', 'extra_key', 'duplicate_key'})


class ClarificationPredicateTests(unittest.TestCase):
    def check(self, step_id, question, suggestions=()):
        return check_clarification(STEPS[STEP_INDEX[step_id]], {'kind': 'clarify', 'question': question, 'suggestions': list(suggestions)})
    def test_ambiguous_scope_needs_both_alternatives(self):
        self.assertEqual(self.check('T35', 'Do you mean the whole opportunities containing this product, or only the product rows?')[0], 'pass')
        self.assertEqual(self.check('C4', 'Should I count the entire opportunities or just that product alone?')[0], 'pass')
        status, problems = self.check('T35', 'Could you clarify what you mean?')
        self.assertEqual(status, 'review'); self.assertIn('accepted variant', problems[0])
        self.assertEqual(self.check('T35', 'Do you mean the whole opportunities?')[0], 'review')
    def test_unsupported_calculation_and_sql_wording(self):
        self.assertEqual(self.check('T34', 'Probability-weighted revenue is not supported. I can show totals by owner.', ['Show the total amount by owner'])[0], 'pass')
        self.assertEqual(self.check('C2', 'I cannot calculate a weighted revenue here.')[0], 'pass')
        self.assertEqual(self.check('T34', 'Which owner do you mean?')[0], 'review')
        self.assertEqual(self.check('T36', "I can't run SQL statements; tell me what the query should return.")[0], 'pass')
        self.assertEqual(self.check('T36', 'Sure, which table?')[0], 'review')
    def test_unsupported_suggestions_fail(self):
        status, problems = self.check('T34', 'Weighted revenue is not available.', ['Show the average amount by owner'])
        self.assertEqual(status, 'fail'); self.assertIn('unsupported suggestion', problems[0])
        self.assertEqual(self.check('T36', 'I cannot run SQL.', ['Run this SQL instead'])[0], 'fail')


class RunnerAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.home = Path(self.temp.name)
        self.records = synthetic_records(); self.witnesses = witnesses_for(self.records)
        self.settings = Settings(self.home, {'DB_KIND': 'postgres', 'PGURL': 'db.example:5432/postgres', 'LLM_MODEL_NAME': 'qwen-test', 'LLM_API_URL': 'http://127.0.0.1:4002/v1/chat/completions'}, rules='- local rule')
        self.repository = FrameRepository(self.records)
    def tearDown(self): self.temp.cleanup()
    def runner(self, planner=None, **kwargs):
        planner = planner or ScriptedPlanner(self.witnesses, **kwargs)
        return AcceptanceRunner(self.settings, self.repository, QueryService(planner, QueryExecutor()), self.home / 'data'), planner
    def drive(self, runner, owner='alice', browser='pass', stop_after=None, before_step=None, **start):
        status = runner.start(owner, **start); run_id = status['run']['id']
        for index in range(len(STEPS)):
            if stop_after is not None and index >= stop_after: break
            if before_step: before_step(index)
            runner.step(owner, run_id, index)
        if browser:
            for check in status['run']['browser']:
                runner.record_browser(owner, run_id, check['id'], browser, {'e': 1}, {'o': 1}, 'recorded by test')
        return run_id

    def test_full_pass_accounts_for_every_step_and_records_identity_versions(self):
        runner, planner = self.runner()
        run_id = self.drive(runner)
        status = runner.status('alice', run_id)
        self.assertTrue(status['full_pass']); self.assertTrue(status['qualified']); self.assertEqual(status['unqualified_reasons'], [])
        counts = status['counts']
        self.assertTrue(counts['accounted']); self.assertEqual(counts['by_state']['pass'], len(STEPS)); self.assertEqual(counts['browser_passed'], len(BROWSER_CHECKS)); self.assertEqual(len(BROWSER_CHECKS), 16)
        identity = status['run']['identity']
        self.assertEqual((identity['suite_version'], identity['evaluator_version'], identity['digest_version']), (SUITE_VERSION, 'reference-2', 'digest2'))
        self.assertEqual(identity['prompt_digest'], 'sha256:scripted-planner'); self.assertIn('stream', identity['model_config']); self.assertEqual(status['run']['report_version'], REPORT_VERSION)
        self.assertTrue(all(k in identity for k in IDENTITY_KEYS))
        self.assertEqual(status['run']['snapshot']['parity']['ok'], True); self.assertTrue(status['run']['snapshot']['retained_snapshot'])
        self.assertTrue(all(g['effective_date'] == date.fromisoformat(identity['effective_date']) for g in planner.generations))
        report = runner.report('alice', run_id)
        for heading in ('### Step status accounting', '### Canonical parity diagnostics', '## Release decision', '### Coverage limitations', 'Fingerprint field order', 'digest2', 'Planner prompt digest', 'Subsidiary Code'):
            self.assertIn(heading, report)
        self.assertIn(f'| total accounted | {len(STEPS)} of {len(STEPS)} |', report); self.assertIn('This run is **qualified**', report)
        self.assertEqual(manifest()['suite_version'], '2.0.0'); self.assertEqual(len(manifest()['browser_checks']), 16)

    def test_recovered_steps_are_distinguished_and_double_rejection_errors(self):
        runner, planner = self.runner(rejections={'T01': ['{"intent":"dance"}'], 'T02': ['{"intent":"dance"}', '{"limit":"ten"}']})
        run_id = self.drive(runner)
        steps = {s['id']: s for s in runner.status('alice', run_id)['run']['steps']}
        self.assertEqual((steps['T01']['status'], steps['T01']['recovered'], len(steps['T01']['attempts'])), ('pass', True, 2))
        self.assertEqual((steps['T02']['status'], len(steps['T02']['attempts'])), ('error', 0)); self.assertIn('after one correction attempt', steps['T02']['error'])
        run = runner.status('alice', run_id)['run']
        self.assertEqual((run['planner']['corrections'], run['planner']['recovered_steps']), (1, ['T01']))
        report = runner.report('alice', run_id); self.assertIn('2 (recovered)', report); self.assertIn('T01 was recovered by one correction attempt', report)
        self.assertFalse(runner.status('alice', run_id)['full_pass'])

    def test_review_status_for_unrecognized_clarification_wording(self):
        runner, _ = self.runner(overrides={'T35': {'intent': 'clarify', 'clarification': 'Could you clarify what you mean?'}, 'T34': {'intent': 'clarify', 'clarification': 'Which owner do you mean?', 'suggestions': ['Show the average amount', 'Show the total amount by owner']}})
        run_id = self.drive(runner)
        status = runner.status('alice', run_id); steps = {s['id']: s for s in status['run']['steps']}
        self.assertEqual(steps['T35']['status'], 'review'); self.assertEqual(steps['T34']['status'], 'review')
        self.assertEqual(steps['T34']['suggestions'], ['Show the total amount by owner'])   # the service already dropped the unsupported suggestion
        self.assertEqual(status['counts']['review'], 2); self.assertTrue(status['complete']); self.assertFalse(status['full_pass'])
        self.assertTrue(any('T35' in r for r in status['unqualified_reasons']))
        self.assertIn('needs manual review', runner.report('alice', run_id))

    def test_data_failure_blocks_dependent_conversation_steps(self):
        runner, _ = self.runner()
        original = QueryExecutor.execute
        target = STEP_INDEX['A1']; state = {'tamper': False}
        def tampered(self_, views, plan):
            result = original(self_, views, plan)
            if state['tamper']: result['rows'] = [dict(r, opportunity_amount='1') for r in result['rows']]
            return result
        with patch.object(QueryExecutor, 'execute', tampered):
            run_id = self.drive(runner, before_step=lambda index: state.update(tamper=(index == target)))
        steps = {s['id']: s for s in runner.status('alice', run_id)['run']['steps']}
        self.assertEqual(steps['A1']['status'], 'fail'); self.assertTrue(steps['A1']['interpretation']['ok']); self.assertFalse(steps['A1']['data_ok'])
        for later in ('A2', 'A3', 'A4', 'A5', 'A6'): self.assertEqual(steps[later]['status'], 'blocked')
        for unaffected in ('B1', 'C6', 'T33'): self.assertEqual(steps[unaffected]['status'], 'pass')

    def test_parity_failure_marks_the_run_unqualified_with_keyed_diagnostics(self):
        runner, _ = self.runner()
        import acceptance_runner
        original = acceptance_runner.build_canonical_views
        def skewed(raw):
            views = original(raw)
            views.sku.loc[views.sku.index[0], 'sku_amount'] = Decimal('123456')
            return views
        with patch.object(acceptance_runner, 'build_canonical_views', skewed):
            run_id = self.drive(runner)
        status = runner.status('alice', run_id); snapshot = status['run']['snapshot']
        self.assertFalse(snapshot['canonical_parity']); self.assertFalse(snapshot['parity']['sku']['ok']); self.assertTrue(snapshot['parity']['opportunity']['ok'])
        example = snapshot['parity']['sku']['examples'][0]
        self.assertEqual((example['kind'], example['column'], example['app_token']), ('cell', 'sku_amount', 'n:123456')); self.assertTrue(example['raw_rows'])
        self.assertTrue(any('canonical parity' in r for r in status['unqualified_reasons'])); self.assertFalse(status['full_pass'])
        self.assertTrue(any(s['status'] == 'pass' for s in status['run']['steps']))   # individual results are preserved
        report = runner.report('alice', run_id); self.assertIn('MISMATCH', report); self.assertIn('run unqualified', report)

    def test_replay_uses_the_retained_snapshot_and_never_qualifies(self):
        runner, _ = self.runner()
        first = self.drive(runner)
        loads = self.repository.loads
        replay = self.drive(runner, replay_from=first)
        self.assertEqual(self.repository.loads, loads)
        status = runner.status('alice', replay)
        self.assertEqual(status['run']['scope'], 'replay of ' + first); self.assertEqual(status['run']['identity']['source_fingerprint'], runner.status('alice', first)['run']['identity']['source_fingerprint'])
        self.assertTrue(status['complete']); self.assertFalse(status['full_pass']); self.assertTrue(any('replay' in r for r in status['unqualified_reasons']))
        self.assertEqual(status['counts']['by_state']['pass'], len(STEPS))
        self.assertEqual(runner.qualification('alice')['streak'], 1)
        with self.assertRaises(AppError): runner.start('alice', replay_from='0' * 32)

    def test_comparison_labels_new_coverage_and_older_runs_do_not_count(self):
        small = FrameRepository(self.records[:12]); self.repository = small
        runner, _ = self.runner(ScriptedPlanner(witnesses_for(self.records[:12])))
        first = self.drive(runner)
        self.assertGreater(runner.status('alice', first)['counts']['blocked'], 0)
        self.repository = FrameRepository(self.records)
        full, _ = self.runner()
        second = self.drive(full)
        comparison = full.comparison('alice', full.list_runs('alice')[0])
        self.assertTrue(comparison['new_coverage']); self.assertEqual(comparison['inconsistent'], []); self.assertGreater(comparison['compared'], 0); self.assertFalse(comparison['same_sequence'])
        old = json.loads((self.home / 'data/acceptance/runs' / (second + '.json')).read_text(encoding='utf-8'))
        old['id'] = '1' * 32; old['report_version'] = 'report-1'; old['started_at'] = '2030-01-01T00:00:00.000+00:00'
        (self.home / 'data/acceptance/runs' / (old['id'] + '.json')).write_text(json.dumps(old), encoding='utf-8')
        q = full.qualification('alice'); self.assertEqual(q['streak'], 0); self.assertIn('older suite', q['reason'])

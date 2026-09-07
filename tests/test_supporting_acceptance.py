"""Supporting evidence has independent membership and arithmetic expectations.

The fixture values deliberately differ between an opportunity and its products.
Primary aggregates can be perfectly correct while their supporting rows are wrong.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from acceptance_runner import AcceptanceRunner, compare_supporting
from acceptance_suite import STEP_INDEX, STEPS, select_witnesses
from app_config import Settings
from data_layer import build_canonical_views
from query_engine import QueryExecutor, parse_plan
from query_service import QueryService
from reference_evaluator import RAW_FIELDS, ReferenceSource, evaluate, evaluate_supporting


def line(opportunity, product, amount, total, quantity):
    return dict.fromkeys(RAW_FIELDS) | {
        'opportunity_no': opportunity, 'opportunity_name': 'Invented ' + opportunity,
        'product_code': product, 'pet_name': 'Product ' + product,
        'opp_amount_converted': amount, 'amount_converted': total,
        'quantity': quantity, 'opp_amount_converted_currency': 'USD', 'amount_converted_currency': 'USD',
        'opportunity_owner': 'Example Owner', 'end_customer': 'Example Customer',
        'stage': 'Qualified', 'first_channel': 'Direct', 'close_month': '1/6/2026', 'close_date': '30/6/2026'}


def invented_rows():
    return [line('001', 'X', '40', '100', '2'), line('001', 'Y', '60', '100', '3'),
            line('002', 'X', '10', '10', '1'), line('003', 'Z', '200', '200', '4')]


def authored_spec(grain='opportunity', filters=(), **extra):
    filters = [dict(item, value=Decimal(str(item['value']))) if item['op'] in ('gt', 'ge', 'lt', 'le') else dict(item) for item in filters]
    return {'intent': 'metric', 'grain': grain, 'filters': filters, 'group': [],
            'measures': ['amount', 'opportunity_count'], 'sort': None, 'limit': None} | extra


def payload(records, spec):
    plan = parse_plan({'result_kind': 'aggregate', 'presentation': 'chart' if spec['intent'] == 'chart' else ('table' if spec['group'] else 'cards'),
                       'grain': 'opportunity' if spec['grain'] == 'opportunity' else 'opportunity_sku',
                       'filters': [{'field': item['field'], 'operator': item['op'], 'value': str(item['value']) if isinstance(item['value'], Decimal) else item['value']} for item in spec['filters']],
                       'group_by': spec['group'], 'measures': spec['measures'], 'limit': spec.get('limit'),
                       'sort': [{'field': field, 'direction': 'asc' if ascending else 'desc'} for field, ascending in spec.get('sort') or []],
                       'chart_type': 'bar' if spec['intent'] == 'chart' else None})
    return QueryService(None, QueryExecutor()).answer_payload(plan, build_canonical_views(records), '2026-09-07T10:00:00Z')


class SupportingReferenceTests(unittest.TestCase):
    def setUp(self):
        self.records = invented_rows()
        self.source = ReferenceSource(self.records)

    def test_whole_opportunity_threshold_preserves_smaller_products(self):
        spec = authored_spec(filters=[{'field': 'amount', 'op': 'gt', 'value': '90'}])
        expected = evaluate_supporting(self.source, spec)
        self.assertEqual([row['opportunity_no'] for row in expected['summary']['rows']], ['001', '003'])
        self.assertEqual([(row['opportunity_no'], row['product_code'], row['sku_amount']) for row in expected['detail']['rows']],
                         [('001', 'X', Decimal('40')), ('001', 'Y', Decimal('60')), ('003', 'Z', Decimal('200'))])
        self.assertEqual(expected['summary']['totals'], {'amount': Decimal('300'), 'quantity': Decimal('9'), 'opportunity_count': 2, 'rows': 2})
        self.assertEqual(expected['detail']['totals']['amount'], Decimal('300'))

    def test_sku_threshold_summary_is_selected_subtotal_with_literal_keys(self):
        spec = authored_spec('sku', [{'field': 'sku_amount', 'op': 'gt', 'value': '50'}])
        expected = evaluate_supporting(self.source, spec)
        self.assertEqual([(row['opportunity_no'], row['product_codes'], row['opportunity_amount']) for row in expected['summary']['rows']],
                         [('001', 'Y', Decimal('60')), ('003', 'Z', Decimal('200'))])
        self.assertEqual(expected['summary']['totals']['amount'], Decimal('260'))
        self.assertEqual(expected['summary']['totals']['quantity'], Decimal('7'))
        self.assertEqual(expected['summary']['data_scope'], 'matching_products')

    def test_product_filter_scope_differs_by_authored_grain(self):
        product_filter = [{'field': 'product_code', 'op': 'eq', 'value': 'X'}]
        whole = evaluate_supporting(self.source, authored_spec(filters=product_filter))
        products = evaluate_supporting(self.source, authored_spec('sku', product_filter))
        self.assertEqual((whole['summary']['totals']['amount'], whole['detail']['total']), (Decimal('110'), 3))
        self.assertEqual((products['summary']['totals']['amount'], products['detail']['total']), (Decimal('50'), 2))
        self.assertEqual(products['summary']['rows'][0]['opportunity_no'], '001')

    def test_aggregate_group_order_and_limit_never_trim_evidence(self):
        spec = authored_spec('sku', group=['product_code'], sort=[('amount', False)], limit=1)
        self.assertEqual(len(evaluate(self.source, spec)['rows']), 1)
        expected = evaluate_supporting(self.source, spec)
        self.assertEqual((expected['summary']['total'], expected['detail']['total']), (3, 4))
        self.assertEqual(expected['summary']['totals']['amount'], Decimal('310'))
        self.assertEqual([row['opportunity_no'] for row in expected['summary']['rows']], ['001', '002', '003'])

    def test_empty_and_mixed_currency_count_support_is_honest(self):
        empty = evaluate_supporting(self.source, authored_spec(filters=[{'field': 'opportunity_no', 'op': 'eq', 'value': 'absent'}]))
        self.assertEqual(empty['detail']['rows'], [])
        self.assertEqual(empty['summary']['totals'], {'amount': None, 'quantity': None, 'opportunity_count': 0, 'rows': 0})
        records = [line('USD-1', 'P', '10', '10', '1'), line('EUR-1', 'P', '20', '20', '2')]
        records[1].update(opp_amount_converted_currency='EUR', amount_converted_currency='EUR')
        expected = evaluate_supporting(ReferenceSource(records), authored_spec(measures=['opportunity_count']))
        self.assertIsNone(expected['summary']['totals']['amount'])
        self.assertEqual(expected['detail']['totals']['opportunity_count'], 2)


class SupportingAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.records = invented_rows()
        self.source = ReferenceSource(self.records)

    def test_actual_supporting_tables_match_independent_authored_scope(self):
        for spec in (authored_spec(), authored_spec(filters=[{'field': 'amount', 'op': 'gt', 'value': '90'}]),
                     authored_spec('sku', [{'field': 'sku_amount', 'op': 'gt', 'value': '50'}]),
                     authored_spec('sku', [{'field': 'product_code', 'op': 'eq', 'value': 'X'}], intent='chart', group=['product_code']),
                     authored_spec(filters=[{'field': 'opportunity_no', 'op': 'eq', 'value': 'absent'}])):
            with self.subTest(spec=spec):
                result = compare_supporting(evaluate_supporting(self.source, spec), payload(self.records, spec))
                self.assertTrue(result['ok'], result)

    def test_correct_scalar_does_not_hide_corrupt_or_missing_support(self):
        spec = authored_spec()
        expected = evaluate_supporting(self.source, spec)
        original = payload(self.records, spec)
        for fault in ('missing', 'wrong_cell', 'wrong_snapshot', 'wrong_scope', 'wrong_answer', 'missing_rows', 'missing_provenance'):
            actual = deepcopy(original)
            if fault == 'missing':
                actual.pop('supporting')
            else:
                table = actual['supporting']['views']['detail']
                if fault == 'wrong_cell': table['rows'][0]['sku_amount'] = '4000'
                elif fault == 'wrong_snapshot': table['metadata']['fingerprint'] = 'different-snapshot'
                elif fault == 'wrong_scope': table['metadata']['evidence']['data_scope'] = 'matching_products'
                elif fault == 'wrong_answer': table['metadata']['evidence']['source_result_digest'] = 'other-answer'
                elif fault == 'missing_rows': table['rows'].pop()
                elif fault == 'missing_provenance': table['metadata'].pop('freshness')
            with self.subTest(fault=fault):
                self.assertEqual(actual['table'], original['table'])
                self.assertFalse(compare_supporting(expected, actual)['ok'])

    def test_support_after_public_and_primary_preview_boundaries_is_checked(self):
        records = [line(f'{index:05}', 'P', str(index + 1), str(index + 1), '1') for index in range(1003)]
        spec = authored_spec(group=['opportunity_owner'], limit=1)
        expected = evaluate_supporting(ReferenceSource(records), spec)
        actual = payload(records, spec)
        self.assertEqual(actual['table']['total_rows'], 1)
        self.assertEqual(len(actual['supporting']['views']['summary']['rows']), 1003)
        self.assertTrue(compare_supporting(expected, actual)['ok'])
        actual['supporting']['views']['summary']['rows'][1002]['opportunity_amount'] = '-1'
        result = compare_supporting(expected, actual)
        self.assertFalse(result['ok'])
        self.assertEqual(result['views']['summary']['counts']['incorrect_cells'], 1)

    def test_runner_fails_support_corruption_and_reports_independent_evidence(self):
        # Exercise one authored aggregate case through the actual acceptance runner.
        from tests.acceptance_fixture import ScriptedPlanner, synthetic_records
        from tests.test_acceptance_runner import FrameRepository
        records = synthetic_records()
        witnesses = select_witnesses(ReferenceSource(records), records)[0]
        class CorruptingService(QueryService):
            def ask(self, *args, **kwargs):
                outcome = super().ask(*args, **kwargs)
                if 'supporting' in outcome:
                    outcome['supporting']['views']['detail']['rows'][0]['sku_amount'] = '9999999'
                return outcome
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            settings = Settings(home, {'DB_KIND': 'demo'})
            service = CorruptingService(ScriptedPlanner(witnesses), QueryExecutor())
            runner = AcceptanceRunner(settings, FrameRepository(records), service, home / 'data')
            run_id = runner.start('reviewer')['run']['id']
            run = runner._load('reviewer', run_id)
            index = STEP_INDEX['T27']
            snapshot = runner.snapshots[run_id]
            runner._execute('reviewer', run, index, snapshot)
            record = run['steps'][index]
            self.assertEqual(record['status'], 'fail')
            self.assertTrue(record['data']['checks']['digest'], 'The primary grouped amount remains correct.')
            self.assertFalse(record['data']['checks']['supporting_rows'])
            section = '\n'.join(runner._step_section(record))
            self.assertIn('Supporting rows: **fail**', section)
            self.assertIn('Supporting-row differences', section)
            self.assertIn('Rows checked cell by cell', section)

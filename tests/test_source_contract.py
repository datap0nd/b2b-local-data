"""Hand-authored business examples: expected amounts are arithmetic, not production-derived.

These raw field spellings intentionally mirror the observed export. Changing both
production and reference mappings backwards must still fail the literal assertions.
"""
from decimal import Decimal
import csv
from pathlib import Path
import tempfile
import unittest

from data_layer import RAW_COLUMNS, build_canonical_views, DATA_CONTRACT_VERSION, read_csv_source
from reference_evaluator import ReferenceSource, evaluate, evaluate_view


def source_line(product='SKU-1', line='40', total='100', **changes):
    return dict.fromkeys(RAW_COLUMNS) | {
        'opportunity_no': '00042', 'product_code': product, 'quantity': '2',
        'amount_converted': total, 'opp_amount_converted': line,
        'amount_converted_currency': 'USD', 'opp_amount_converted_currency': 'USD',
        'first_channel': 'Direct', 'stage': 'Qualified', 'close_month': '1/6/2026',
        'created_date': '1/1/2025', 'opportunity_name': 'Invented project',
    } | changes


class SourceContractTests(unittest.TestCase):
    def test_integrated_scalar_answer_keeps_every_requested_measure(self):
        from answer_text import compose_answer
        from query_engine import QueryExecutor, parse_plan
        measures = ['amount', 'quantity', 'opportunity_count', 'sku_count', 'deal_size']
        views = build_canonical_views([source_line(line='100', deal_size_on_pricing_date_usd='120')])
        result = QueryExecutor().execute(views, parse_plan({'result_kind': 'aggregate', 'presentation': 'cards', 'measures': measures}))
        answer = compose_answer(result)
        self.assertEqual(len(answer['metrics']), 5, 'Scalar UI uses these metrics as the sole visible values, so no requested measure may be truncated.')
        self.assertEqual([metric['raw'] for metric in answer['metrics']], ['100', '2', 1, 1, '120'])

    def test_integrated_multiple_channels_bucket_can_be_selected(self):
        from query_engine import QueryExecutor, parse_plan
        rows = [source_line(), source_line('SKU-2', '60', first_channel='Partner')]
        executor, views = QueryExecutor(), build_canonical_views(rows)
        for operator, value in [('eq', 'Multiple channels'), ('in', ['Multiple channels'])]:
            result = executor.execute(views, parse_plan({'result_kind': 'aggregate', 'measures': ['opportunity_count'], 'filters': [
                {'field': 'first_channel', 'operator': operator, 'value': value}]}))
            self.assertEqual(result['rows'], [{'opportunity_count': 1}])
        excluded = executor.execute(views, parse_plan({'result_kind': 'aggregate', 'measures': ['opportunity_count'], 'filters': [
            {'field': 'first_channel', 'operator': 'ne', 'value': 'Multiple channels'}]}))
        self.assertEqual(excluded['rows'], [{'opportunity_count': 0}])

    def test_integrated_missing_line_guards_precede_money_selection_and_sort(self):
        from app_config import AppError
        from query_engine import QueryExecutor, parse_plan
        rows = [source_line(), source_line('SKU-2', None), source_line(opportunity_no='SAFE', line='100')]
        executor, views = QueryExecutor(), build_canonical_views(rows)
        for field in ['amount', 'opportunity_amount', 'sku_amount']:
            with self.subTest(field=field), self.assertRaises(AppError):
                executor.execute(views, parse_plan({'result_kind': 'aggregate', 'measures': ['opportunity_count'], 'filters': [
                    {'field': field, 'operator': 'ge', 'value': '500'}]}))
        with self.assertRaises(AppError):
            executor.execute(views, parse_plan({'result_kind': 'rows', 'sort': [{'field': 'opportunity_amount', 'direction': 'desc'}]}))
        result = executor.execute(views, parse_plan({'result_kind': 'aggregate', 'measures': ['amount'], 'filters': [
            {'field': 'amount', 'operator': 'ge', 'value': '50'}, {'field': 'opportunity_no', 'operator': 'eq', 'value': 'SAFE'}]}))
        self.assertEqual(result['rows'], [{'amount': '100'}])

    def test_integrated_summary_does_not_claim_missing_unselected_lines(self):
        from query_engine import QueryExecutor, parse_plan
        views = build_canonical_views([source_line(), source_line('SKU-2', None)])
        plan = parse_plan({'result_kind': 'rows', 'grain': 'opportunity_sku', 'filters': [
            {'field': 'product_code', 'operator': 'eq', 'value': 'SKU-1'}]})
        summary = QueryExecutor().variant(views, plan, 'summary')
        self.assertEqual(summary['totals']['amount'], '40')
        self.assertEqual(summary['metadata']['complete']['by_currency']['USD']['amount'], '40')
        issues = summary['metadata']['warnings'][0]['records'][0]['issues']
        self.assertTrue(all(issue['message'].startswith('Whole opportunity: ') for issue in issues))

    def test_integrated_currency_groups_do_not_publish_cross_currency_extrema(self):
        from query_engine import QueryExecutor, parse_plan
        rows = [source_line(opportunity_no='USD-ONE', line='40', total='40', deal_size_on_pricing_date_usd='50'),
                source_line(opportunity_no='EUR-ONE', line='60', total='60', amount_converted_currency='EUR',
                            opp_amount_converted_currency='EUR', deal_size_on_pricing_date_usd='70')]
        result = QueryExecutor().execute(build_canonical_views(rows), parse_plan({'result_kind': 'aggregate',
            'group_by': ['opp_amount_converted_currency'], 'measures': ['amount', 'deal_size']}))
        complete = result['metadata']['complete']
        self.assertIsNone(complete['measure_totals']['amount'])
        self.assertNotIn('amount', complete['largest'], 'Independent currency groups have no comparable monetary maximum without conversion.')
        self.assertEqual(complete['largest']['deal_size']['deal_size'], '70')

    def test_integrated_legacy_history_keeps_evidence_out_of_current_planner_totals(self):
        from history_store import HistoryStore
        from query_engine import parse_plan
        plan = parse_plan({'result_kind': 'aggregate', 'measures': ['amount'], 'filters': [
            {'field': 'stage', 'operator': 'eq', 'value': 'Open'}]})
        with tempfile.TemporaryDirectory() as temporary:
            store = HistoryStore(Path(temporary) / 'history.sqlite3')
            session = store.create('owner')
            turn = store.append('owner', session, 'What is the open amount?', 'Total amount 987654321.', plan, kind='data')
            original = {'table': {'rows': [{'amount': '987654321'}], 'metadata': {}}, 'variants': {}}
            store.save_result('owner', session, turn, 'data', plan, None, None, original)
            history, active = store.context('owner', session)
            text = '\n'.join(item['content'] for item in history)
            self.assertNotIn('987654321', text)
            self.assertIn('earlier', text)
            self.assertEqual(active.filters[0].value, 'Open')
            self.assertEqual(store.load_result('owner', session, turn)['table']['rows'], [{'amount': '987654321'}])

    def test_csv_adapter_preserves_asymmetric_amount_and_currency_provenance(self):
        rows = [source_line(amount_converted_currency='EUR'), source_line('SKU-2', '60', amount_converted_currency='EUR')]
        headers = {name: name for name in RAW_COLUMNS} | {
            'amount_converted': 'Amount (converted)', 'opp_amount_converted': 'Opp Amount (converted)',
            'amount_converted_currency': 'Amount (converted) Currency',
            'opp_amount_converted_currency': 'Opp Amount (converted) Currency', 'first_channel': '1st Channel',
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'asymmetric.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow([headers[name] for name in RAW_COLUMNS])
                writer.writerows([row[name] for name in RAW_COLUMNS] for row in rows)
            raw = read_csv_source(path)
        self.assertEqual(raw.iloc[0].amount_converted, '100')
        self.assertEqual(raw.iloc[0].opp_amount_converted, '40')
        actual = build_canonical_views(raw)
        self.assertEqual(actual.opportunity.iloc[0].opportunity_amount, Decimal(100))
        self.assertEqual(actual.opportunity.iloc[0].opp_amount_converted_currency, 'USD')
        self.assertEqual(actual.opportunity.iloc[0].exported_opp_amount_currency, 'EUR')

    def test_asymmetric_repeated_total_and_line_quantities(self):
        rows = [source_line(), source_line('SKU-2', '60', quantity='3')]
        actual = build_canonical_views(rows)
        expected = ReferenceSource(rows)
        for sku_rows, opportunity in [(actual.sku.to_dict('records'), actual.opportunity.iloc[0]),
                                      (expected.sku, expected.opportunity[0])]:
            self.assertEqual([r['sku_amount'] for r in sku_rows], [Decimal(40), Decimal(60)])
            self.assertEqual(opportunity['opportunity_amount'], Decimal(100))
            self.assertEqual(opportunity['exported_opp_amount_min'], Decimal(100))
            self.assertEqual(opportunity['quantity'], Decimal(5))
            self.assertEqual(opportunity['sku_count'], 2)
            self.assertFalse(opportunity['has_quality_warning'])
        self.assertEqual(actual.quality_details, {'opportunity': {}, 'opportunity_sku': {}})
        self.assertEqual(actual.data_contract_version, DATA_CONTRACT_VERSION)

    def test_repeated_sku_and_identical_lines_remain_additive(self):
        # No line-item identifier is supplied. Two identical rows can be two valid
        # source lines; removing either would make the hand-derived total wrong.
        rows = [source_line(line='20'), source_line(line='20'), source_line('SKU-2', '60')]
        actual = build_canonical_views(rows)
        self.assertEqual(actual.sku.iloc[0].source_row_count, 2)
        self.assertEqual(actual.sku.iloc[0].sku_amount, Decimal(40))
        self.assertEqual(actual.opportunity.iloc[0].source_row_count, 3)
        self.assertEqual(actual.opportunity.iloc[0].opportunity_amount, Decimal(100))
        self.assertFalse(actual.opportunity.iloc[0].has_amount_discrepancy)

    def test_currency_validated_before_sku_or_opportunity_sums(self):
        for second_product in ['SKU-1', 'SKU-2']:
            for other_currency in ['EUR', None]:
                with self.subTest(product=second_product, currency=other_currency):
                    rows = [source_line(line='10', total='20'), source_line(second_product, '10', '20', opp_amount_converted_currency=other_currency)]
                    actual, independent = build_canonical_views(rows), ReferenceSource(rows)
                    self.assertIsNone(actual.opportunity.iloc[0].opportunity_amount)
                    self.assertIsNone(independent.opportunity[0]['opportunity_amount'])
                    self.assertTrue(actual.opportunity.iloc[0].has_invalid_amount_currency)
                    self.assertEqual(set(actual.opportunity.iloc[0].amount_currency_values), {'USD', other_currency})
                    self.assertTrue(any(i['code'] == 'currency_issue' for i in actual.quality_details['opportunity']['00042']))
                    if second_product == 'SKU-1':
                        self.assertIsNone(actual.sku.iloc[0].sku_amount)

    def test_source_currencies_follow_their_business_amounts(self):
        rows = [source_line(line='40', total='80', amount_converted_currency='EUR')]
        actual = build_canonical_views(rows)
        self.assertEqual(actual.sku.iloc[0].amount_converted_currency, 'USD')
        self.assertEqual(actual.opportunity.iloc[0].opp_amount_converted_currency, 'USD')
        self.assertEqual(actual.opportunity.iloc[0].exported_opp_amount_currency, 'EUR')
        self.assertEqual(actual.opportunity.iloc[0].opportunity_amount, Decimal(40))
        issues = actual.quality_details['opportunity']['00042']
        self.assertEqual([issue['code'] for issue in issues], ['currency_issue'])
        self.assertNotIn('amount_mismatch', [issue['code'] for issue in issues])

    def test_quality_reasons_distinguish_source_fields_and_overlap(self):
        rows = [source_line(), source_line('SKU-2', '60', total='101')]
        actual = build_canonical_views(rows)
        issues = actual.quality_details['opportunity']['00042']
        self.assertEqual([issue['code'] for issue in issues], ['conflicting_parent_amount'])
        self.assertEqual(issues[0]['values'], [Decimal(100), Decimal(101)])
        rows[1]['amount_converted'] = '100'
        rows[1]['opp_amount_converted'] = '61'
        actual = build_canonical_views(rows)
        issue = actual.quality_details['opportunity']['00042'][0]
        self.assertEqual(issue['code'], 'amount_mismatch')
        self.assertEqual((issue['product_total'], issue['exported_total'], issue['difference']), (Decimal(101), Decimal(100), Decimal(1)))
        self.assertEqual(issue['currency'], 'USD')

    def test_missing_line_is_visible_even_when_known_subtotal_matches_parent(self):
        rows = [source_line(line='100'), source_line('SKU-2', None)]
        actual = build_canonical_views(rows)
        self.assertEqual(actual.opportunity.iloc[0].opportunity_amount, Decimal(100))
        self.assertTrue(actual.opportunity.iloc[0].has_amount_discrepancy)
        self.assertTrue(actual.sku.iloc[1].has_quality_warning)
        self.assertEqual(actual.quality_details['opportunity']['00042'][0]['field'], 'source_line_amount')
        self.assertTrue(actual.opportunity.iloc[0].has_missing_line_amount)
        rows[0]['opp_amount_converted'] = '40'
        actual = build_canonical_views(rows)
        # The remaining amount is unknown, so 40 vs 100 is a partial subtotal,
        # not a confirmed reconciliation difference between complete amounts.
        self.assertEqual([issue['code'] for issue in actual.quality_details['opportunity']['00042']], ['missing_amount'])

    def test_missing_parent_does_not_invalidate_complete_line_sum(self):
        rows = [source_line(total=None), source_line('SKU-2', '60', total=None)]
        actual = build_canonical_views(rows)
        self.assertFalse(actual.opportunity.iloc[0].has_missing_line_amount)
        self.assertEqual(actual.opportunity.iloc[0].opportunity_amount, Decimal(100))
        self.assertEqual(actual.quality_details['opportunity']['00042'][0]['field'], 'source_opportunity_total')
        independent = evaluate(ReferenceSource(rows), {'grain': 'opportunity', 'intent': 'metric', 'measures': ['amount']})
        self.assertEqual(independent['rows'], [{'amount': Decimal(100)}])

    def test_reference_rejects_invalid_line_money_but_keeps_counts(self):
        for changes in [{'opp_amount_converted': None}, {'opp_amount_converted_currency': None}, {'opp_amount_converted_currency': 'EUR'}]:
            with self.subTest(changes=changes):
                source = ReferenceSource([source_line(), source_line('SKU-2', '60', **changes)])
                with self.assertRaises(ValueError):
                    evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'measures': ['amount']})
                self.assertEqual(evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'measures': ['opportunity_count']})['rows'], [{'opportunity_count': 1}])

    def test_reference_amount_filters_cannot_hide_missing_inputs(self):
        source = ReferenceSource([source_line(), source_line('SKU-2', None), source_line(opportunity_no='SAFE', line='100')])
        for field in ['amount', 'opportunity_amount', 'sku_amount']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'filters': [
                    {'field': field, 'op': 'ge', 'value': Decimal(500)}], 'measures': ['opportunity_count']})
        # A non-monetary selector establishes an unaffected scope before checking
        # money, regardless of whether the model lists the money predicate first.
        result = evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'filters': [
            {'field': 'amount', 'op': 'ge', 'value': Decimal(50)},
            {'field': 'opportunity_no', 'op': 'eq', 'value': 'SAFE'}], 'measures': ['opportunity_count']})
        self.assertEqual(result['rows'], [{'opportunity_count': 1}])

    def test_matching_product_summary_validates_its_own_currency_scope(self):
        source = ReferenceSource([source_line(), source_line('SKU-2', '60', opp_amount_converted_currency='EUR')])
        spec = {'grain': 'sku', 'intent': 'table', 'columns': ['sku_amount'], 'filters': [
            {'field': 'product_code', 'op': 'eq', 'value': 'SKU-1'}]}
        subset = evaluate_view(source, spec, 'summary')
        self.assertEqual(subset['rows'][0]['opportunity_amount'], Decimal(40))
        self.assertEqual(subset['rows'][0]['opp_amount_converted_currency'], 'USD')
        self.assertEqual(subset['totals']['amount'], Decimal(40))
        whole = evaluate_view(source, dict(spec, filters=[]), 'summary')
        self.assertIsNone(whole['rows'][0]['opportunity_amount'])
        self.assertIsNone(whole['rows'][0]['opp_amount_converted_currency'])
        self.assertIsNone(whole['totals']['amount'])

    def test_all_channel_memberships_survive_reduction(self):
        rows = [source_line(), source_line('SKU-2', '60', first_channel='Partner')]
        actual, independent = build_canonical_views(rows), ReferenceSource(rows)
        for opportunity in [actual.opportunity.iloc[0], independent.opportunity[0]]:
            self.assertEqual(opportunity['first_channel'], 'Multiple channels')
            self.assertEqual(opportunity['first_channel_values'], ('Direct', 'Partner'))
            self.assertEqual(opportunity['opportunity_amount'], Decimal(100))
        self.assertEqual(actual.quality_details['opportunity']['00042'][0]['code'], 'channel_conflict')
        # Same-SKU repeated lines must preserve both memberships too.
        rows[1]['product_code'] = 'SKU-1'
        actual = build_canonical_views(rows)
        self.assertEqual(actual.sku.iloc[0].first_channel_values, ('Direct', 'Partner'))
        source = ReferenceSource(rows)
        for channel in ['Direct', 'Partner']:
            result = evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'filters': [
                {'field': 'first_channel', 'op': 'eq', 'value': channel}], 'measures': ['opportunity_count', 'amount']})
            self.assertEqual(result['rows'], [{'opportunity_count': 1, 'amount': Decimal(100)}])
        grouped = evaluate(source, {'grain': 'opportunity', 'intent': 'metric', 'group': ['first_channel'], 'measures': ['amount']})
        self.assertEqual(grouped['rows'], [{'first_channel': 'Multiple channels', 'amount': Decimal(100)}])

    def test_parent_metadata_conflicts_are_detected_across_different_skus(self):
        rows = [source_line(), source_line('SKU-2', '60', stage='Lost', close_month='1/7/2026')]
        actual = build_canonical_views(rows)
        self.assertFalse(actual.sku.has_quality_warning.any())
        self.assertTrue(actual.opportunity.iloc[0].has_quality_warning)
        fields = {issue['field'] for issue in actual.quality_details['opportunity']['00042']}
        self.assertEqual(fields, {'stage', 'close_month'})

    def test_close_month_does_not_define_open_status(self):
        rows = [source_line(line='100', stage='Won'), source_line(opportunity_no='OTHER', line='100', close_month=None)]
        actual = build_canonical_views(rows)
        self.assertEqual(actual.opportunity.iloc[0].stage, 'Won')
        self.assertIsNotNone(actual.opportunity.iloc[0].close_month)
        self.assertEqual(actual.opportunity.iloc[1].stage, 'Qualified')
        self.assertIsNone(actual.opportunity.iloc[1].close_month)

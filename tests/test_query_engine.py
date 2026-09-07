from decimal import Decimal
import unittest

from app_config import AppError
from data_layer import build_canonical_views,demo_rows
from query_engine import QueryExecutor,merge_plan,parse_plan


class QueryEngineTests(unittest.TestCase):
    def setUp(self):self.views=build_canonical_views(demo_rows());self.executor=QueryExecutor()
    def execute(self,**values):return self.executor.execute(self.views,parse_plan(values))

    def test_won_expands_stage_members(self):
        result=self.execute(filters=[{'field':'stage','operator':'eq','value':'Won'}])
        self.assertEqual(result['total_rows'],2)

    def test_all_stage_groups(self):
        rows=demo_rows()
        stages=['Won','Rollout Started','Rollout Finished','Identified','Qualified','Negotiation','Dropped','Lost']
        self.views=build_canonical_views([dict(rows[0],opportunity_no=str(index),stage=stage) for index,stage in enumerate(stages)])
        for group,count in [('Won',3),('Open',3),('Lost',2)]:
            self.assertEqual(self.execute(filters=[{'field':'stage','operator':'eq','value':group}])['total_rows'],count)

    def test_aggregate_filter_runs_after_business_grain(self):
        result=self.execute(filters=[{'field':'quantity','operator':'gt','value':3}])
        self.assertEqual([row['opportunity_no'] for row in result['rows']],['OPP-001'])

    def test_product_filter_selects_whole_opportunity_or_matching_sku(self):
        filters=[{'field':'product_code','operator':'eq','value':'SKU-A'}]
        self.assertEqual(self.execute(filters=filters)['rows'][0]['opportunity_amount'],'750')
        self.assertEqual(self.execute(grain='opportunity_sku',filters=filters)['rows'][0]['sku_amount'],'600')

    def test_grouped_metrics_do_not_double_count_opportunities(self):
        result=self.execute(intent='metric',grain='opportunity_sku',dimensions=['stage_group'],measures=['amount','opportunity_count','sku_count'])
        won=next(row for row in result['rows'] if row['stage_group']=='Won')
        self.assertEqual(won['amount'],'1200')
        self.assertEqual(won['opportunity_count'],2)
        self.assertEqual(won['sku_count'],3)

    def test_metric_without_groups_and_decimal_money(self):
        result=self.execute(intent='metric',measures=['amount','quantity','opportunity_count'])
        self.assertEqual(result['rows'],[{'amount':'3600','quantity':'9','opportunity_count':3}])

    def test_between_dates_and_literal_contains(self):
        result=self.execute(filters=[{'field':'close_date','operator':'between','value':['2026-10-01','2026-10-31']},{'field':'end_customer','operator':'contains','value':'north'}])
        self.assertEqual(result['total_rows'],2)
        self.assertEqual(self.execute(filters=[{'field':'end_customer','operator':'contains','value':'.*'}])['total_rows'],0)

    def test_sort_and_limit_follow_aggregation(self):
        result=self.execute(sort=[{'field':'opportunity_amount','direction':'desc'}],limit=1)
        self.assertEqual(result['rows'][0]['opportunity_no'],'OPP-003')
        self.assertTrue(result['truncated'])
        self.assertEqual(result['total_rows'],3)

    def test_table_projection_retains_business_keys(self):
        result=self.execute(grain='opportunity_sku',dimensions=['pet_name'],measures=['amount'])
        self.assertEqual(result['columns'],['opportunity_no','product_code','pet_name','amount'])

    def test_refine_inherits_and_replaces_same_field(self):
        previous=parse_plan({'filters':[{'field':'stage','operator':'eq','value':'Won'},{'field':'opportunity_owner','operator':'eq','value':'Alex'}],'sort':[{'field':'quantity'}],'limit':5})
        refined=merge_plan(previous,parse_plan({'context_action':'refine','remove_filters':['stage'],'filters':[{'field':'opportunity_owner','operator':'eq','value':'Blair'}]}))
        self.assertEqual([f.field for f in refined.filters],['opportunity_owner'])
        self.assertEqual(refined.filters[0].value,'Blair')
        self.assertEqual(refined.limit,5)
        self.assertEqual(refined.sort[0].field,'quantity')

    def test_replace_resets_and_explicit_empty_clears(self):
        previous=parse_plan({'dimensions':['stage'],'limit':5})
        self.assertEqual(merge_plan(previous,parse_plan({})).dimensions,[])
        refined=merge_plan(previous,parse_plan({'context_action':'refine','dimensions':[]}))
        self.assertEqual(refined.dimensions,[])
        self.assertEqual(refined.limit,5)

    def test_clarification_preserves_previous_plan(self):
        previous=parse_plan({'limit':5})
        question=parse_plan({'intent':'clarify','clarification':'Which date?','context_action':'refine'})
        self.assertEqual(merge_plan(previous,question).intent.value,'clarify')
        self.assertEqual(previous.limit,5)

    def test_malicious_text_stays_literal(self):
        self.assertEqual(self.execute(filters=[{'field':'opportunity_name','operator':'eq','value':"__import__('os').system('anything')"}])['total_rows'],0)
        for payload in [{'sql':'DROP TABLE x'},{'version':2},{'limit':True},{'filters':[{'field':'stage','operator':'in','value':[]}]},{'filters':[{'field':'stage','operator':'between','value':['Won']}]},{'intent':'clarify'}]:
            with self.subTest(payload=payload),self.assertRaises(AppError):parse_plan(payload)

    def test_unknown_fields_and_invalid_types_rejected(self):
        for values in [{'dimensions':['password']},{'sort':[{'field':'password'}]},{'filters':[{'field':'quantity','operator':'eq','value':'nan'}]}, {'filters':[{'field':'close_date','operator':'ge','value':'2026-02-30'}]}]:
            with self.subTest(values=values),self.assertRaises(AppError):self.execute(**values)

    def test_chart_contract_and_quality_flags(self):
        result=self.execute(intent='chart',chart_type='bar',dimensions=['stage_group'],measures=['amount'])
        self.assertEqual(result['chart']['type'],'bar')
        self.assertTrue(result['warnings'])

    def test_mixed_currency_requires_group_or_filter(self):
        rows=demo_rows();rows[-1]['opp_amount_converted_currency']='USD';self.views=build_canonical_views(rows)
        with self.assertRaises(AppError):self.execute(intent='metric',measures=['amount'])
        self.assertEqual(self.execute(intent='metric',dimensions=['opp_amount_converted_currency'],measures=['amount'])['total_rows'],2)

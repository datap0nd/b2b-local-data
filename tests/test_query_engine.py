from decimal import Decimal
import unittest

from app_config import AppError
from data_layer import build_canonical_views,demo_rows
from query_engine import QUERY_FIELDS,QueryExecutor,merge_plan,parse_plan
from query_models import Measure


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

    def test_added_attributes_select_filter_and_sort_at_both_grains(self):
        columns=['first_channel','age','comment','deal_size_on_pricing_date_usd']
        for grain,keys in [('opportunity',['opportunity_no']),('opportunity_sku',['opportunity_no','product_code'])]:
            result=self.execute(grain=grain,dimensions=columns,sort=[{'field':'age','direction':'asc'}])
            self.assertEqual(result['columns'],keys+columns)
            self.assertEqual([row['age'] for row in result['rows']][:2],['12','30'])
            self.assertEqual(result['column_types']['age'],'number');self.assertEqual(result['column_types']['comment'],'text')
        self.assertEqual([r['opportunity_no'] for r in self.execute(filters=[{'field':'first_channel','operator':'eq','value':'Direct'}])['rows']],['OPP-002'])
        self.assertEqual(self.execute(filters=[{'field':'comment','operator':'contains','value':'fictional'}])['total_rows'],3)
        self.assertEqual(self.execute(filters=[{'field':'age','operator':'between','value':[10,40]}])['total_rows'],2)
        self.assertEqual(self.execute(grain='opportunity_sku',filters=[{'field':'deal_size_on_pricing_date_usd','operator':'gt','value':700}])['total_rows'],3)
        self.assertEqual(self.execute(filters=[{'field':'deal_size','operator':'ge','value':'2400'}])['total_rows'],1)

    def test_age_is_reported_not_summed(self):
        self.assertNotIn('age',{m.value for m in Measure})
        rows=demo_rows();rows[1]['age']='99'
        self.views=build_canonical_views(rows)
        self.assertEqual(self.execute(dimensions=['age'])['rows'][0]['age'],'30')
        with self.assertRaises(AppError):self.execute(intent='metric',measures=['age'])

    def test_deal_size_counts_once_per_opportunity(self):
        self.assertEqual(self.execute(intent='metric',measures=['deal_size'])['rows'],[{'deal_size':'3650'}])
        self.assertEqual(self.execute(grain='opportunity_sku',intent='metric',measures=['deal_size','amount','opportunity_count'])['rows'],[{'deal_size':'3650','amount':'3600','opportunity_count':3}])
        grouped=self.execute(grain='opportunity_sku',intent='chart',chart_type='bar',dimensions=['stage_group'],measures=['deal_size'])
        self.assertEqual({row['stage_group']:row['deal_size'] for row in grouped['rows']},{'Won':'1250','Open':'2400'})
        by_channel=self.execute(intent='metric',dimensions=['first_channel'],measures=['deal_size','amount'])
        self.assertEqual({row['first_channel']:(row['deal_size'],row['amount']) for row in by_channel['rows']},{'Partner':('3150','3150'),'Direct':('500','450')})

    def test_deal_size_with_product_filters_selects_matching_opportunities(self):
        filters=[{'field':'product_code','operator':'eq','value':'SKU-B'}]
        self.assertEqual(self.execute(intent='metric',filters=filters,measures=['deal_size'])['rows'],[{'deal_size':'1250'}])
        self.assertEqual(self.execute(grain='opportunity_sku',intent='metric',filters=filters,measures=['deal_size','amount'])['rows'],[{'deal_size':'1250','amount':'600'}])
        table=self.execute(measures=['deal_size'],filters=filters,dimensions=['opportunity_no'])
        self.assertEqual([(row['opportunity_no'],row['deal_size']) for row in table['rows']],[('OPP-001','750'),('OPP-002','500')])

    def test_deal_size_rejects_product_breakdowns_and_sku_tables(self):
        for values in [{'intent':'metric','dimensions':['product_code'],'measures':['deal_size']},
                       {'intent':'chart','chart_type':'bar','grain':'opportunity_sku','dimensions':['pet_name'],'measures':['deal_size']},
                       {'intent':'metric','grain':'opportunity_sku','dimensions':['stage_group','gscm_product_group_new'],'measures':['deal_size']},
                       {'grain':'opportunity_sku','measures':['deal_size']}]:
            with self.subTest(values=values),self.assertRaises(AppError) as error:self.execute(**values)
            self.assertIn('Deal size',str(error.exception))
        self.assertEqual(self.execute(grain='opportunity_sku',intent='metric',dimensions=['product_code'],measures=['amount'])['total_rows'],3)

    def test_deal_size_ignores_mixed_currency_rule_and_null_values(self):
        rows=demo_rows();rows[-1]['opp_amount_converted_currency']='USD';rows[-1]['deal_size_on_pricing_date_usd']=None
        self.views=build_canonical_views(rows)
        self.assertEqual(self.execute(intent='metric',measures=['deal_size','opportunity_count'])['rows'],[{'deal_size':'1250','opportunity_count':3}])
        with self.assertRaises(AppError):self.execute(intent='metric',measures=['amount','deal_size'])

    def test_older_plans_and_refinements_remain_valid(self):
        legacy='{"version":1,"intent":"metric","context_action":"replace","grain":"opportunity","filters":[{"field":"stage","operator":"eq","value":"Won"}],"remove_filters":[],"dimensions":["stage_group"],"measures":["amount","opportunity_count"],"sort":[],"limit":null,"chart_type":null,"clarification":null,"suggestions":[]}'
        plan=parse_plan(legacy)
        self.assertEqual(self.executor.execute(self.views,plan)['rows'],[{'stage_group':'Won','amount':'1200','opportunity_count':2}])
        refined=merge_plan(plan,parse_plan({'context_action':'refine','measures':['deal_size'],'remove_filters':['stage']}))
        self.assertEqual(self.executor.execute(self.views,refined)['rows'],[{'stage_group':'Open','deal_size':'2400'},{'stage_group':'Won','deal_size':'1250'}])
        self.assertTrue({'deal_size','amount','stage_group','first_channel','comment'}<=QUERY_FIELDS)

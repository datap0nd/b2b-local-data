"""Hand-calculated fixtures prove the independent evaluator, and tampered results prove it detects defects."""
from datetime import date
from decimal import Decimal
import unittest

from data_layer import build_canonical_views, demo_rows
from query_engine import QueryExecutor, parse_plan
from reference_evaluator import ReferenceSource, compare, evaluate, fingerprint, normalize_cell, r_date


def record(**values):
    base={'opportunity_no':'O1','product_code':'P1','stage':'Won','opportunity_owner':'Ann','end_customer':'North Ltd','opportunity_name':'Alpha',
          'pet_name':'Widget','quantity':'2','amount_converted':'100.50','opp_amount_converted':'300.50','amount_converted_currency':'EUR',
          'opp_amount_converted_currency':'EUR','probability':'80%','close_date':'5/3/2026','close_month':'1/3/2026','created_date':'01/01/2025',
          'last_modified_date':'02/01/2025','first_channel':'Direct','age':'10','comment':'x','deal_size_on_pricing_date_usd':'1000','type':'New'}
    return base|values


HAND_RECORDS=[record(),record(amount_converted='200',quantity='1',last_modified_date='9/9/2025'),                 # O1/P1 twice: amount 300.50, qty 3
              record(product_code='P2',amount_converted='abc',quantity=None,pet_name='Gadget'),               # O1/P2: amount null, qty null
              record(opportunity_no='O2',stage='Qualified',opportunity_owner='Bob',amount_converted='50',quantity='5',opp_amount_converted='50',
                     probability=None,close_date='31/04/2026',deal_size_on_pricing_date_usd='20',age='7'),   # invalid close date -> null
              record(opportunity_no='O2',product_code='P3',stage='Qualified',opportunity_owner='Bob',amount_converted='25.25',quantity='1',opp_amount_converted='75',
                     probability=None,deal_size_on_pricing_date_usd='20',age='7'),                              # parent min/max differ -> discrepancy
              record(opportunity_no='O3',stage='Lost',opportunity_owner='Ann',amount_converted='10',quantity='1',opp_amount_converted='10.01',deal_size_on_pricing_date_usd=None),
              record(opportunity_no=' ',product_code='P9')]                                                    # excluded


class EvaluatorFixtureTests(unittest.TestCase):
    def setUp(self):self.source=ReferenceSource(HAND_RECORDS)
    def test_grain_reduction_by_hand(self):
        self.assertEqual((self.source.raw_count,self.source.excluded,len(self.source.sku),len(self.source.opportunity)),(7,1,5,3))
        o1=self.source.opportunity_index['O1']
        self.assertEqual(o1['opportunity_amount'],Decimal('300.50'));self.assertEqual(o1['quantity'],Decimal(3))
        self.assertEqual(o1['sku_count'],2);self.assertEqual(o1['source_row_count'],3);self.assertEqual(o1['product_names'],'Gadget, Widget')
        self.assertFalse(o1['has_amount_discrepancy']);self.assertEqual(o1['last_modified_date'],date(2025,9,9));self.assertEqual(o1['close_month'],date(2026,3,1))
        o2=self.source.opportunity_index['O2']
        self.assertEqual(o2['opportunity_amount'],Decimal('75.25'));self.assertTrue(o2['has_amount_discrepancy']);self.assertIsNone(o2['probability'])
        self.assertEqual(o2['close_date'],date(2026,3,5));self.assertEqual(o2['deal_size_on_pricing_date_usd'],Decimal(20))
        self.assertIsNone(next(s for s in self.source.sku if s['opportunity_no']=='O2' and s['product_code']=='P1')['close_date'])
        o3=self.source.opportunity_index['O3']
        self.assertFalse(o3['has_amount_discrepancy']);self.assertIsNone(o3['deal_size_on_pricing_date_usd'])
        p2=next(s for s in self.source.sku if s['product_code']=='P2')
        self.assertIsNone(p2['sku_amount']);self.assertIsNone(p2['quantity']);self.assertEqual(p2['source_row_count'],1)
    def test_table_filters_sort_limit_and_totals_by_hand(self):
        result=evaluate(self.source,{'grain':'opportunity','intent':'table','filters':[{'field':'stage','op':'eq','value':'Won'}],'columns':['opportunity_owner','opportunity_amount']})
        self.assertEqual(result['columns'],['opportunity_no','opportunity_owner','opportunity_amount'])
        self.assertEqual(result['rows'],[{'opportunity_no':'O1','opportunity_owner':'Ann','opportunity_amount':Decimal('300.50')}])
        self.assertEqual(result['totals'],{'amount':Decimal('300.50'),'quantity':Decimal(3),'opportunity_count':1,'rows':1})
        top=evaluate(self.source,{'grain':'opportunity','intent':'table','columns':['opportunity_amount'],'sort':[('opportunity_amount',False),('opportunity_no',True)],'limit':2})
        self.assertEqual([r['opportunity_no'] for r in top['rows']],['O1','O2']);self.assertEqual(top['total'],3)
        whole=evaluate(self.source,{'grain':'opportunity','intent':'table','filters':[{'field':'product_code','op':'eq','value':'P2'}],'columns':['opportunity_amount']})
        self.assertEqual(whole['rows'],[{'opportunity_no':'O1','opportunity_amount':Decimal('300.50')}])
        only=evaluate(self.source,{'grain':'sku','intent':'table','filters':[{'field':'product_code','op':'eq','value':'P2'}],'columns':['sku_amount']})
        self.assertEqual(only['rows'],[{'opportunity_no':'O1','product_code':'P2','sku_amount':None}])
        nulls_last=evaluate(self.source,{'grain':'opportunity','intent':'table','columns':['probability'],'sort':[('probability',False)]})
        self.assertEqual([r['opportunity_no'] for r in nulls_last['rows']],['O1','O3','O2'])
        text=evaluate(self.source,{'grain':'opportunity','intent':'table','filters':[{'field':'end_customer','op':'contains','value':'NORTH'}],'columns':[]})
        self.assertEqual(text['total'],3)
    def test_metrics_by_hand(self):
        result=evaluate(self.source,{'grain':'sku','intent':'metric','group':['stage_group'],'measures':['amount','quantity','opportunity_count','sku_count','deal_size']})
        self.assertEqual(result['rows'],[{'stage_group':'Lost','amount':Decimal(10),'quantity':Decimal(1),'opportunity_count':1,'sku_count':1,'deal_size':None},
                                         {'stage_group':'Open','amount':Decimal('75.25'),'quantity':Decimal(6),'opportunity_count':1,'sku_count':2,'deal_size':Decimal(20)},
                                         {'stage_group':'Won','amount':Decimal('300.50'),'quantity':Decimal(3),'opportunity_count':1,'sku_count':2,'deal_size':Decimal(1000)}])
        total=evaluate(self.source,{'grain':'opportunity','intent':'metric','measures':['amount','deal_size']})
        self.assertEqual(total['rows'],[{'amount':Decimal('385.75'),'deal_size':Decimal(1020)}])
    def test_dates_and_fingerprint(self):
        self.assertEqual(r_date('1/12/2022'),date(2022,12,1));self.assertEqual(r_date('29/02/2024'),date(2024,2,29))
        for value in ['29/02/2023','31/04/2026','0/1/2026','1/1/26','2026-01-01',None,'']:self.assertIsNone(r_date(value))
        first=fingerprint(HAND_RECORDS);shuffled=fingerprint(list(reversed(HAND_RECORDS)))
        self.assertEqual(first,shuffled);self.assertTrue(first.startswith('fp1:'))
        self.assertNotEqual(first,fingerprint(HAND_RECORDS[:-1]));self.assertNotEqual(first,fingerprint(HAND_RECORDS+[HAND_RECORDS[0]]))
        self.assertEqual(fingerprint([record(comment=' padded ')]),fingerprint([record(comment='padded')]))
        self.assertEqual(normalize_cell(Decimal('750.00')),'750');self.assertEqual(normalize_cell('0.750'),'0.75');self.assertEqual(normalize_cell(date(2026,1,2)),'2026-01-02')


class DefectDetectionTests(unittest.TestCase):
    """The production engine is only used here as a system under test."""
    def setUp(self):
        self.rows=demo_rows();self.views=build_canonical_views(self.rows);self.source=ReferenceSource(self.rows);self.executor=QueryExecutor()
    def run_case(self,plan,spec):
        return compare(evaluate(self.source,spec),self.executor.execute(self.views,parse_plan(plan)))
    def test_production_matches_reference_on_correct_plans(self):
        cases=[({},{'grain':'opportunity','intent':'table','columns':['opportunity_name','end_customer','opportunity_owner','stage','close_date','product_codes','product_names','quantity','opportunity_amount','sku_count','opp_amount_converted_currency','has_amount_discrepancy','has_quality_warning']}),
               ({'grain':'opportunity_sku','filters':[{'field':'stage','operator':'eq','value':'Won'}]},{'grain':'sku','intent':'table','filters':[{'field':'stage','op':'eq','value':'Won'}],'columns':['pet_name','end_customer','opportunity_owner','stage','quantity','sku_amount','amount_converted_currency','has_quality_warning']}),
               ({'intent':'metric','grain':'opportunity_sku','dimensions':['stage_group'],'measures':['amount','opportunity_count','sku_count','deal_size']},{'grain':'sku','intent':'metric','group':['stage_group'],'measures':['amount','opportunity_count','sku_count','deal_size']}),
               ({'intent':'chart','chart_type':'line','dimensions':['close_month'],'measures':['amount'],'sort':[{'field':'close_month','direction':'asc'}]},{'grain':'opportunity','intent':'chart','group':['close_month'],'measures':['amount'],'sort':[('close_month',True)]}),
               ({'sort':[{'field':'opportunity_amount','direction':'desc'},{'field':'opportunity_no','direction':'asc'}],'limit':2,'dimensions':['opportunity_amount']},{'grain':'opportunity','intent':'table','columns':['opportunity_amount'],'sort':[('opportunity_amount',False),('opportunity_no',True)],'limit':2})]
        for plan,spec in cases:
            with self.subTest(plan=plan):
                outcome=self.run_case(plan,spec);self.assertTrue(outcome['ok'],outcome)
    def test_wrong_filter_is_detected_even_with_same_row_count(self):
        outcome=self.run_case({'filters':[{'field':'opportunity_owner','operator':'eq','value':'Blair'}]},{'grain':'opportunity','intent':'table','filters':[{'field':'end_customer','op':'eq','value':'Example East'}],'columns':['opportunity_owner']})
        self.assertFalse(outcome['ok']);self.assertEqual(outcome['counts']['missing'],1);self.assertEqual(outcome['counts']['extra'],1)
    def test_doubled_amounts_missing_extra_rows_and_wrong_measure_are_detected(self):
        spec={'grain':'opportunity','intent':'table','columns':['opportunity_amount']}
        expected=evaluate(self.source,spec);actual=self.executor.execute(self.views,parse_plan({'dimensions':['opportunity_amount']}))
        self.assertTrue(compare(expected,actual)['ok'])
        doubled=dict(actual,rows=[dict(r,opportunity_amount=str(Decimal(r['opportunity_amount'])*2)) for r in actual['rows']])
        outcome=compare(expected,doubled);self.assertFalse(outcome['ok']);self.assertEqual(outcome['counts']['incorrect_cells'],3);self.assertEqual(outcome['differences'][0]['kind'],'cell')
        missing=dict(actual,rows=actual['rows'][1:]);self.assertEqual(compare(expected,missing)['counts']['missing'],1)
        extra=dict(actual,rows=actual['rows']+[dict(actual['rows'][0],opportunity_no='OPP-999')]);self.assertEqual(compare(expected,extra)['counts']['extra'],1)
        duplicate=dict(actual,rows=actual['rows']+actual['rows'][:1]);self.assertFalse(compare(expected,duplicate)['checks']['no_duplicates'])
        reordered=dict(actual,rows=list(reversed(actual['rows'])));self.assertFalse(compare(expected,reordered)['checks']['order'])
        tampered_totals=dict(actual,totals=dict(actual['totals'],amount='1'));self.assertFalse(compare(expected,tampered_totals)['checks']['totals'])
        wrong_measure=self.run_case({'intent':'chart','chart_type':'bar','dimensions':['stage_group'],'measures':['quantity']},{'grain':'opportunity','intent':'chart','group':['stage_group'],'measures':['amount']})
        self.assertFalse(wrong_measure['ok']);self.assertFalse(wrong_measure['checks']['columns'])
        wrong_count=dict(actual,total_rows=99);self.assertFalse(compare(expected,wrong_count)['checks']['total_rows'])

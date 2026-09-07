"""Supporting lists reconcile with the exact aggregate population and frozen answer."""
import csv
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app_config import AppError, Settings
from data_layer import RAW_COLUMNS, build_canonical_views, dataset_fingerprint
from history_store import HistoryStore, SavedResultTooLarge, ordered_supporting_rows, supporting_csv
from query_engine import QueryExecutor, parse_plan
from query_service import QueryService, public_answer_payload
from test_api import LocalServer


def line(opp,product,amount,total,**values):
    return dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':opp,'product_code':product,'opp_amount_converted':str(amount),
        'amount_converted':str(total),'quantity':'1','stage':'Qualified','close_month':'1/6/2026','close_date':'2/6/2026',
        'amount_converted_currency':'USD','opp_amount_converted_currency':'USD','opportunity_name':'Invented '+opp,
        'opportunity_owner':'Reviewer','pet_name':'Product '+product,'first_channel':'Direct','probability':'75%',
        'deal_size_on_pricing_date_usd':str(total)}|values


def views_for(rows):
    views=build_canonical_views(rows)
    views.fingerprint=dataset_fingerprint(rows)
    views.freshness={'status':'verified','updated_at':'2026-09-07T10:00:00+00:00','method':'test_fixture','timezone':'UTC'}
    return views


class SupportingPopulationTests(unittest.TestCase):
    def payload(self,rows,**plan):
        return QueryService(None,QueryExecutor()).answer_payload(parse_plan(plan),views_for(rows),'2026-09-07T10:01:00+00:00')

    def test_count_threshold_is_applied_to_whole_opportunity_only_once(self):
        rows=[line('MATCH','A',60000,130000),line('MATCH','B',70000,130000),line('LOW','A',90000,90000),
              line('OLD','A',200000,200000,close_month='1/6/2025'),line('LOST','A',200000,200000,stage='Lost')]
        payload=self.payload(rows,result_kind='aggregate',measures=['opportunity_count'],filters=[
            {'field':'stage_group','operator':'eq','value':'Open'},
            {'field':'close_month','operator':'between','value':['2026-01-01','2026-12-31']},
            {'field':'amount','operator':'gt','value':'100000'}])
        self.assertEqual(payload['table']['rows'],[{'opportunity_count':1}])
        support=payload['supporting']['views']
        self.assertEqual([r['opportunity_no'] for r in support['summary']['rows']],['MATCH'])
        self.assertEqual([r['sku_amount'] for r in support['detail']['rows']],['60000','70000'])
        self.assertEqual(support['summary']['rows'][0]['opportunity_amount'],'130000')
        self.assertEqual(support['detail']['totals']['amount'],'130000')
        for table in support.values():
            evidence=table['metadata']['evidence']
            self.assertEqual(evidence['source_result_digest'],payload['table']['result_digest'])
            self.assertEqual(evidence['data_scope'],'all_products')
            self.assertEqual(table['filters'],payload['table']['filters'])
            for name in ['freshness','fingerprint','calculation_version','data_contract_version']:
                self.assertEqual(table['metadata'][name],payload['table']['metadata'][name])

    def test_sku_filtered_amount_supports_matching_products_only(self):
        rows=[line('ONE','A',40,100),line('ONE','B',60,100),line('TWO','A',20,20)]
        payload=self.payload(rows,result_kind='aggregate',grain='opportunity_sku',measures=['amount'],filters=[
            {'field':'product_code','operator':'eq','value':'A'},{'field':'amount','operator':'gt','value':'30'}])
        self.assertEqual(payload['table']['rows'],[{'amount':'40'}])
        support=payload['supporting']['views']
        self.assertEqual(support['summary']['rows'][0]['opportunity_amount'],'40')
        self.assertEqual(support['summary']['rows'][0]['product_codes'],'A')
        self.assertEqual([(r['opportunity_no'],r['product_code']) for r in support['detail']['rows']],[('ONE','A')])
        for table in support.values():
            self.assertEqual(table['totals']['amount'],'40')
            self.assertEqual(table['views']['scope_label'],'Matching products only')

    def test_group_preview_does_not_limit_supporting_population(self):
        rows=[line('ONE','A',40,100),line('ONE','B',60,100),line('TWO','C',20,20)]
        payload=self.payload(rows,result_kind='aggregate',grain='opportunity_sku',group_by=['product_code'],measures=['opportunity_count'],limit=1)
        self.assertEqual(len(payload['table']['rows']),1)
        self.assertTrue(payload['table']['truncated'])
        summary,detail=payload['supporting']['views']['summary'],payload['supporting']['views']['detail']
        self.assertEqual(summary['total_rows'],2)
        self.assertEqual(detail['total_rows'],3)
        self.assertEqual(summary['totals']['opportunity_count'],2)
        self.assertFalse(summary['truncated'])

    def test_zero_answer_keeps_empty_supporting_schema_and_rows_answer_is_not_duplicated(self):
        rows=[line('ONE','A',40,40)]
        payload=self.payload(rows,result_kind='aggregate',measures=['opportunity_count'],filters=[{'field':'stage','operator':'eq','value':'Lost'}])
        self.assertEqual(payload['table']['rows'],[{'opportunity_count':0}])
        for table in payload['supporting']['views'].values():
            self.assertEqual(table['rows'],[])
            self.assertEqual(table['total_rows'],0)
            self.assertIn('opportunity_no',table['columns'])
        self.assertNotIn('supporting',self.payload(rows,result_kind='rows'))

    def test_full_support_survives_1000_row_preview_bound_and_explicit_size_failure(self):
        rows=[line(f'{i:05d}','A',i+1,i+1) for i in range(1105)]
        views=views_for(rows)
        plan=parse_plan({'result_kind':'aggregate','measures':['opportunity_count']})
        service=QueryService(None,QueryExecutor())
        with tempfile.TemporaryDirectory() as temporary:
            store=HistoryStore(Path(temporary)/'history.sqlite3')
            session=store.create('owner')
            payload=service.execute_and_save(store,'owner',session,'Count',plan,views,'fixed')
            self.assertEqual(len(payload['supporting']['views']['summary']['rows']),1105)
            saved=store.load_result('owner',session,payload['turn_id'])
            self.assertEqual(len(saved['supporting']['views']['detail']['rows']),1105)
            preview=public_answer_payload(payload)
            self.assertEqual(len(preview['supporting']['views']['summary']['rows']),25)
            self.assertTrue(preview['supporting']['views']['summary']['truncated'])
            original=store.save_result
            calls=0
            def limited(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==1: raise SavedResultTooLarge('forced full evidence bound')
                return original(*args,**kwargs)
            with patch.object(store,'save_result',side_effect=limited):
                failure=service.execute_and_save(store,'owner',session,'Count again',plan,views,'fixed')
            self.assertFalse(failure['supporting']['available'])
            self.assertIn('too large',failure['supporting']['message'])
            self.assertEqual(len(failure['supporting']['views']['summary']['rows']),25)
            restored=store.load_supporting('owner',session,failure['turn_id'])
            self.assertFalse(restored['available'])

    def test_csv_matches_formula_guards_and_decimal_sort_uses_no_float(self):
        table={'grain':'opportunity','columns':['opportunity_no','opportunity_amount','comment','has_quality_warning'],
               'rows':[{'opportunity_no':'0002','opportunity_amount':'9007199254740993.02','comment':' =SUM(A1:A2)','has_quality_warning':False},
                       {'opportunity_no':'0001','opportunity_amount':'9007199254740993.01','comment':'Zoë "quoted"','has_quality_warning':True}]}
        rows=ordered_supporting_rows(table,'opportunity_amount','asc')
        self.assertEqual([r['opportunity_no'] for r in rows],['0001','0002'])
        body=supporting_csv(table,rows)
        self.assertTrue(body.startswith('\ufeff"opportunity_no"'))
        self.assertIn('\r\n',body)
        decoded=list(csv.reader(io.StringIO(body.lstrip('\ufeff'))))
        self.assertEqual(decoded[1],['0001','9007199254740993.01','Zoë "quoted"','true'])
        self.assertEqual(decoded[2][2],"' =SUM(A1:A2)")

    def test_supporting_money_sort_retains_incomplete_line_guard(self):
        rows=[line('ONE','A',40,100),line('ONE','B','',100)]
        payload=self.payload(rows,result_kind='aggregate',measures=['opportunity_count'])
        table=payload['supporting']['views']['summary']
        self.assertEqual(table['rows'][0]['opportunity_amount'],'40')
        self.assertFalse(table['metadata']['evidence']['amount_complete'])
        with self.assertRaisesRegex(AppError,'incomplete'):
            ordered_supporting_rows(table,'opportunity_amount','desc')
        self.assertEqual(len(ordered_supporting_rows(table,'opportunity_no','asc')),1)
        # A valid selected product is unaffected by an unselected missing line.
        subset=self.payload(rows,result_kind='aggregate',grain='opportunity_sku',measures=['opportunity_count'],filters=[
            {'field':'product_code','operator':'eq','value':'A'}])['supporting']['views']['summary']
        self.assertTrue(subset['metadata']['evidence']['amount_complete'])
        self.assertEqual(len(ordered_supporting_rows(subset,'opportunity_amount','desc')),1)

    def test_negative_supporting_amount_roundtrips_but_text_and_expressions_stay_guarded(self):
        payload=self.payload([line('-001','A','-12.50','-12.50',comment='-12.50')],result_kind='aggregate',measures=['amount'])
        table=payload['supporting']['views']['detail']
        body=supporting_csv(table,table['rows'])
        exported=list(csv.DictReader(io.StringIO(body.lstrip('\ufeff'))))[0]
        self.assertEqual(exported['sku_amount'],'-12.50')
        self.assertEqual(Decimal(exported['sku_amount']),Decimal('-12.50'))
        self.assertEqual(exported['opportunity_no'],"'-001")
        self.assertEqual(exported['comment'],"'-12.50")
        table={'columns':['value','+header'],'column_types':{'value':'number','+header':'number'},'rows':[
            {'value':'-1.25e-3','+header':'+12.50'},{'value':'-1+2','+header':'@SUM(A1)'},
            {'value':' -12.50','+header':'=1+2'}]}
        exported=list(csv.reader(io.StringIO(supporting_csv(table,table['rows']).lstrip('\ufeff'))))
        self.assertEqual(exported[0],['value',"'+header"])
        self.assertEqual(exported[1],['-1.25e-3','+12.50'])
        self.assertEqual(exported[2],["'-1+2","'@SUM(A1)"])
        self.assertEqual(exported[3],["' -12.50","'=1+2"])


class SupportingApiTests(unittest.TestCase):
    def test_pages_csv_history_and_owner_isolation_use_only_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows=[line(f'{i:05d}','A',Decimal(i)+Decimal('.01'),Decimal(i)+Decimal('.01')) for i in range(1105)]
            repository=MagicMock();repository.load.return_value=views_for(rows)
            planner=MagicMock();planner.plan.return_value=parse_plan({'result_kind':'aggregate','measures':['opportunity_count']})
            app=LocalServer(Settings(Path(temporary),{'DB_KIND':'demo'}),repository=repository,planner=planner,name='Owner')
            try:
                answer=app.request('/api/ask',{'question':'Count every opportunity'})
                self.assertEqual(answer['table']['rows'],[{'opportunity_count':1105}])
                self.assertEqual(len(answer['supporting']['views']['summary']['rows']),25)
                base=f"/api/sessions/{answer['session_id']}/turns/{answer['turn_id']}"
                repository.load.side_effect=AssertionError('Supporting reads must not reload the source')
                page=app.request(base+'/supporting?view=summary&page=22&page_size=50&sort=opportunity_amount&direction=desc')
                self.assertEqual(page['total_rows'],1105)
                self.assertEqual([r['opportunity_no'] for r in page['table']['rows']],['00004','00003','00002','00001','00000'])
                restored=app.request(base+'/result')
                self.assertEqual(len(restored['supporting']['views']['summary']['rows']),25)
                self.assertEqual(restored['supporting']['views']['summary']['metadata']['fingerprint'],answer['table']['metadata']['fingerprint'])
                with app.opener.open(app.base+base+'/supporting.csv?view=detail&sort=sku_amount&direction=desc') as response:
                    body=response.read().decode('utf-8-sig')
                exported=list(csv.DictReader(io.StringIO(body)))
                self.assertEqual(len(exported),1105)
                self.assertEqual(exported[0]['opportunity_no'],'01104')
                self.assertEqual(exported[-1]['opportunity_no'],'00000')
                self.assertEqual(exported[0]['sku_amount'],'1104.01')
                for query in ['view=bogus','page=-1','page_size=201','sort=password','direction=sideways']:
                    with self.subTest(query=query),self.assertRaises(HTTPError):
                        app.request(base+'/supporting?'+query)
                self.assertEqual(repository.load.call_count,1)
                self.assertEqual(planner.plan.call_count,1)
                app.login('Other')
                with self.assertRaises(HTTPError):app.request(base+'/supporting')
                with self.assertRaises(HTTPError):app.opener.open(app.base+base+'/supporting.csv')
                app.login('Owner')
                saved=app.app.state.store.load_result('name:Owner',answer['session_id'],answer['turn_id'])
                saved.pop('supporting')
                app.app.state.store.save_result('name:Owner',answer['session_id'],answer['turn_id'],'data',parse_plan(answer['plan']),None,None,saved)
                missing=app.request(base+'/supporting')
                self.assertFalse(missing['available'])
                self.assertTrue(missing['can_rerun'])
                self.assertEqual(repository.load.call_count,1)
            finally:app.stop()

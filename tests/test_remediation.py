"""Hand-derived business cases for the 0.7 calculation and presentation changes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from answer_text import compose_answer
from app_config import AppError, Settings
from data_layer import build_canonical_views, demo_rows
from query_engine import CALCULATION_VERSION, QueryExecutor, parse_plan
from query_service import QueryService
from history_store import HistoryStore
from test_api import LocalServer
from acceptance_runner import AcceptanceRunner


def line(opp, product, amount, total, **values):
    return dict(demo_rows()[0], opportunity_no=opp, product_code=product,
                opp_amount_converted=str(amount), amount_converted=str(total), **values)


class BusinessResultTests(unittest.TestCase):
    def execute(self, rows, **plan):
        return QueryExecutor().execute(build_canonical_views(rows), parse_plan(plan))

    def test_one_opportunity_two_products_never_repeats_parent_total(self):
        rows=[line('ONE','A',40,100),line('ONE','B',60,100)]
        table=self.execute(rows,result_kind='aggregate',presentation='cards',measures=['amount','opportunity_count'])
        self.assertEqual(table['rows'],[{'amount':'100','opportunity_count':1}])
        self.assertEqual(table['metadata']['warnings'],[])
        selected=self.execute(rows,result_kind='aggregate',grain='opportunity_sku',measures=['amount'],filters=[{'field':'product_code','operator':'eq','value':'A'}])
        self.assertEqual(selected['rows'],[{'amount':'40'}])
        whole=self.execute(rows,result_kind='aggregate',grain='opportunity',measures=['amount'],filters=[{'field':'product_code','operator':'eq','value':'A'}])
        self.assertEqual(whole['rows'],[{'amount':'100'}])

    def test_overlapping_product_counts_use_population_distinct_total(self):
        rows=[line('ONE','A',40,100),line('ONE','B',60,100),line('TWO','A',20,20)]
        table=self.execute(rows,result_kind='aggregate',grain='opportunity_sku',group_by=['product_code'],measures=['opportunity_count'])
        self.assertEqual(sum(r['opportunity_count'] for r in table['rows']),3)
        self.assertEqual(table['metadata']['complete']['measure_totals']['opportunity_count'],2)
        self.assertEqual(compose_answer(table)['metrics'],[])

    def test_largest_is_computed_before_alphabetical_preview_limit(self):
        rows=[line('A','X',1,1,opportunity_owner='A')]+[line(str(i),'X',1,1,opportunity_owner='Z') for i in range(3)]
        table=self.execute(rows,result_kind='aggregate',group_by=['opportunity_owner'],measures=['opportunity_count'],limit=1)
        self.assertTrue(table['truncated']); self.assertEqual(table['rows'][0]['opportunity_owner'],'A')
        self.assertEqual(compose_answer(table)['sentence'],'Largest opportunity count: Z with 3.')
        table['metadata']['complete'].pop('largest')
        self.assertEqual(compose_answer(table)['sentence'],'')

    def test_mixed_currencies_are_rejected_before_amount_aggregation_but_counts_work(self):
        rows=[line('ONE','A',10,20,opp_amount_converted_currency='USD'),line('ONE','B',10,20,opp_amount_converted_currency='EUR')]
        with self.assertRaisesRegex(AppError,'currenc'):
            self.execute(rows,result_kind='aggregate',measures=['amount'])
        count=self.execute(rows,result_kind='aggregate',measures=['opportunity_count'])
        self.assertEqual(count['rows'],[{'opportunity_count':1}])
        table=self.execute(rows,result_kind='rows')
        self.assertIsNone(table['totals']['amount'])

    def test_matching_product_summary_uses_selected_currency_and_completeness(self):
        views=build_canonical_views([line('ONE','A',10,20,opp_amount_converted_currency='USD'),line('ONE','B',10,20,opp_amount_converted_currency='EUR')])
        engine=QueryExecutor()
        selected=parse_plan({'result_kind':'rows','grain':'opportunity_sku','filters':[{'field':'product_code','operator':'eq','value':'A'}]})
        summary=engine.variant(views,selected,'summary')
        self.assertEqual(summary['rows'][0]['opportunity_amount'],'10')
        self.assertEqual(summary['metadata']['currency']['code'],'USD')
        self.assertEqual(summary['totals']['amount'],'10')
        all_products=engine.variant(views,parse_plan({'result_kind':'rows','grain':'opportunity_sku'}),'summary')
        self.assertIsNone(all_products['rows'][0]['opportunity_amount'])
        self.assertIsNone(all_products['totals']['amount'])

    def test_missing_line_amount_is_not_claimed_as_complete_but_missing_parent_allows_sum(self):
        rows=[line('ONE','A',40,100),line('ONE','B','',100)]
        with self.assertRaisesRegex(AppError,'amounts are missing'):
            self.execute(rows,result_kind='aggregate',measures=['amount'])
        rows=[line('ONE','A',40,''),line('ONE','B',60,'')]
        table=self.execute(rows,result_kind='aggregate',measures=['amount'])
        self.assertEqual(table['rows'],[{'amount':'100'}])
        self.assertTrue(table['metadata']['warnings'])

    def test_channel_membership_preserves_both_values_and_avoids_arbitrary_group(self):
        rows=[line('ONE','A',40,100,first_channel='Alpha'),line('ONE','B',60,100,first_channel='Zulu')]
        for channel in ['Alpha','Zulu']:
            table=self.execute(rows,result_kind='aggregate',measures=['opportunity_count'],filters=[{'field':'first_channel','operator':'eq','value':channel}])
            self.assertEqual(table['rows'],[{'opportunity_count':1}])
        groups=self.execute(rows,result_kind='aggregate',group_by=['first_channel'],measures=['amount'])
        self.assertEqual(groups['rows'],[{'first_channel':'Multiple channels','amount':'100'}])

    def test_all_quality_records_have_specific_evidence_and_survive_saved_snapshot(self):
        rows=[line(str(i),'A',40,100) for i in range(75)]
        views=build_canonical_views(rows)
        plan=parse_plan({'result_kind':'aggregate','measures':['opportunity_count']})
        service=QueryService(MagicMock(),QueryExecutor())
        with tempfile.TemporaryDirectory() as home:
            store=HistoryStore(Path(home)/'history.sqlite3'); session=store.create('owner')
            result=service.execute_and_save(store,'owner',session,'Count',plan,views,None)
            records=result['table']['metadata']['warnings'][0]['records']
            self.assertEqual(len(records),75)
            self.assertTrue(all(any(i['code']=='amount_mismatch' for i in r['issues']) for r in records))
            saved=store.load_result('owner',session,result['turn_id'])
            self.assertEqual(saved['table']['metadata']['warnings'][0]['records'],records)

    def test_count_title_and_scope_are_stated_once(self):
        table=self.execute([line('ONE','A',100,100,stage='Qualified')],result_kind='aggregate',presentation='cards',measures=['opportunity_count'],filters=[{'field':'stage_group','operator':'eq','value':'Open'},{'field':'close_month','operator':'between','value':['2026-01-01','2026-12-31']}])
        answer=compose_answer(table)
        self.assertEqual(answer['title'],'Open opportunities')
        self.assertEqual(answer['context'],'Closing in 2026')
        self.assertEqual(answer['sentence'],'')
        self.assertEqual([m['value'] for m in answer['metrics']],['1'])


class CurrentDataApiTests(unittest.TestCase):
    def test_reference_agreement_cannot_certify_unverified_live_source_semantics(self):
        runner=object.__new__(AcceptanceRunner)
        run={'snapshot':{'source':'postgres','canonical_parity':True},'identity':{'source_contract_verified':False},'scope':'full','status':'complete','steps':[],'browser':[]}
        self.assertFalse(runner.is_full_pass(run))
        self.assertIn('independently verified',runner.unqualified_reasons(run)[0])
        run['identity']['source_contract_verified']=True
        self.assertEqual(runner.unqualified_reasons(run),[])

    def test_default_test_access_and_freshness_do_not_call_model(self):
        with tempfile.TemporaryDirectory() as home:
            views=build_canonical_views(demo_rows())
            views.freshness={'status':'verified','updated_at':'2026-09-07T10:00:00+00:00','method':'commit_timestamp'}
            repository=MagicMock(); repository.load.return_value=views
            planner=MagicMock()
            app=LocalServer(Settings(Path(home),{'DB_KIND':'demo'}),repository=repository,planner=planner,name='Reviewer')
            try:
                self.assertTrue(app.request('/api/bootstrap')['capabilities']['acceptance_ui'])
                self.assertEqual(app.request('/api/freshness')['freshness'],views.freshness)
                self.assertEqual(app.request('/api/freshness')['freshness'],views.freshness)
                self.assertEqual(repository.load.call_count,1)
                planner.plan.assert_not_called()
            finally:app.stop()

    def test_old_calculation_result_is_preserved_but_requires_explicit_rerun(self):
        with tempfile.TemporaryDirectory() as home:
            repository=MagicMock(); repository.load.return_value=build_canonical_views(demo_rows())
            app=LocalServer(Settings(Path(home),{'DB_KIND':'demo'}),repository=repository,planner=MagicMock(),name='Reviewer')
            try:
                result=app.request('/api/sample',{'intent':'table','view':'summary'})
                sid,tid=result['session_id'],result['turn_id']
                store=app.app.state.store
                owner='name:Reviewer'
                saved=store.load_result(owner,sid,tid)
                self.assertEqual(saved['table']['metadata']['calculation_version'],CALCULATION_VERSION)
                saved['table']['metadata'].pop('calculation_version')
                store.save_result(owner,sid,tid,'data',parse_plan(result['plan']),None,None,saved)
                calls=repository.load.call_count
                response=app.request(f'/api/sessions/{sid}/turns/{tid}/result')
                self.assertFalse(response['available']); self.assertTrue(response['can_rerun'])
                self.assertIn('earlier',response['message'])
                self.assertEqual(repository.load.call_count,calls)
                self.assertIsNotNone(store.load_result(owner,sid,tid))
                context,_=store.context(owner,sid)
                self.assertIn('previous amounts and summary values must not be reused',context[-1]['content'])
            finally:app.stop()


if __name__=='__main__':unittest.main()

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from data_layer import build_canonical_views
from history_store import HistoryStore
from product_scope import resolve_product_scope
from query_engine import QueryExecutor, merge_plan, parse_plan
from query_service import QueryService
from test_supporting_acceptance import line


def catalog():
    names=['Orbit Q7','Orbit Q7+','Orbit Q7 Ultra','Orbit Q7 FE','Orbit Q7 Case']
    rows=[dict(line(str(i),'SKU'+str(i),'10','10','1'),pet_name=n) for i,n in enumerate(names)]
    return build_canonical_views(rows)


def query(value='q7',op='contains',**extra):
    return parse_plan({'filters':[{'field':'stage_group','operator':'eq','value':'Open'},
                                 {'field':'pet_name','operator':op,'value':value}],**extra})


class ProductScopeTests(unittest.TestCase):
    def setUp(self): self.views=catalog()
    def resolve(self,plan,text): return resolve_product_scope(plan,plan,text,self.views)

    def test_short_base_and_undefined_family_ask_before_execution(self):
        for value,op in [('q7','contains'),('q7','eq'),(['q7'],'in'),('q7 family','contains'),('q7 family','eq'),('Orbit Q7','eq')]:
            with self.subTest(value=value,op=op):
                plan=self.resolve(query(value,op),'Give me amount just for Q7')
                self.assertEqual(plan.result_kind.value,'clarify')
                self.assertIn('base model',plan.clarification)
                self.assertIn('variants',plan.clarification)
                self.assertLessEqual(len(plan.clarification),300)

    def test_explicit_list_resolves_aliases_and_excludes_unlisted_products(self):
        plan=self.resolve(query(['q7','Q7+','Q7 Ultra'],'in'),'Open BOs for Q7, Q7+, Q7 Ultra')
        self.assertEqual(plan.filters[1].value,['Orbit Q7','Orbit Q7+','Orbit Q7 Ultra'])
        result=QueryExecutor().execute(self.views,plan)
        self.assertEqual(result['total_rows'],3)
        self.assertEqual({r['product_names'] for r in result['rows']},{'Orbit Q7','Orbit Q7+','Orbit Q7 Ultra'})

    def test_explicit_base_clarification_changes_contains_to_exact(self):
        plan=self.resolve(query(),'Only the base model, please')
        self.assertEqual(plan.filters[1].operator.value,'eq')
        self.assertEqual(plan.filters[1].value,'Orbit Q7')
        self.assertEqual(QueryExecutor().execute(self.views,plan)['total_rows'],1)

    def test_base_amount_per_opportunity_excludes_other_products_in_same_bo(self):
        self.views=build_canonical_views([
            dict(line('BO1','BASE','40','100','2'),pet_name='Orbit Q7'),
            dict(line('BO1','ULTRA','60','100','3'),pet_name='Orbit Q7 Ultra')])
        plan=self.resolve(query(grain='opportunity_sku',result_kind='aggregate',
                                group_by=['opportunity_no'],measures=['amount']),
                          'Amount for only the base model per opportunity')
        result=QueryExecutor().execute(self.views,plan)
        self.assertEqual(result['rows'],[{'opportunity_no':'BO1','amount':'40'}])

    def test_stored_exact_name_and_explicit_substring_are_respected(self):
        exact=query('Orbit Q7','eq')
        self.assertEqual(self.resolve(exact,'Exactly Orbit Q7').filters,exact.filters)
        broad=query()
        self.assertEqual(self.resolve(broad,'Show product names containing q7').filters,broad.filters)
        self.assertEqual(QueryExecutor().execute(self.views,broad)['total_rows'],5)

    def test_alias_shared_by_brands_is_not_guessed(self):
        self.views=build_canonical_views([dict(line(str(i),'SKU'+str(i),'1','1','1'),pet_name=n)
                                         for i,n in enumerate(['Orbit Q7','Nova Q7'])])
        self.assertEqual(self.resolve(query(['q7','q7+'],'in'),'Q7 and Q7+').result_kind.value,'clarify')

    def test_negated_base_request_does_not_narrow_to_base(self):
        self.assertEqual(self.resolve(query(),'Not only the base model').result_kind.value,'clarify')

    def test_unchanged_confirmed_product_scope_is_not_questioned_again(self):
        previous=query('Orbit Q7','eq')
        incoming=parse_plan({'context_action':'refine','filters':[{'field':'stage_group','operator':'eq','value':'Won'}]})
        merged=merge_plan(previous,incoming)
        self.assertEqual(resolve_product_scope(merged,incoming,'Now Won',self.views),merged)

    def test_unknown_exact_name_stays_empty_without_inventing_alias(self):
        plan=query('No such model','eq')
        self.assertEqual(self.resolve(plan,'Exactly No such model').filters,plan.filters)

    def test_clarification_preserves_history_and_finishes_original_refinement(self):
        class Planner:
            next=None
            def plan(self,*args,**kwargs): return self.next
        planner=Planner()
        service=QueryService(planner,QueryExecutor())
        with TemporaryDirectory() as home:
            store=HistoryStore(Path(home)/'history.sqlite3'); session=store.create('owner')
            planner.next=parse_plan({'filters':[{'field':'stage_group','operator':'eq','value':'Open'},
                {'field':'close_month','operator':'between','value':['2026-01-01','2026-12-31']}]})
            service.ask(store,'owner',session,'Open BOs closing in 2026','auto',self.views,None)
            _,previous=store.context('owner',session)
            planner.next=parse_plan({'context_action':'refine','result_kind':'aggregate','grain':'opportunity_sku',
                'group_by':['opportunity_no'],'measures':['amount'],'filters':[{'field':'pet_name','operator':'contains','value':'q7'}]})
            with patch.object(service,'execute_and_save',wraps=service.execute_and_save) as execute:
                answer=service.ask(store,'owner',session,'Amount just for q7 per opportunity','auto',self.views,None)
                self.assertEqual(answer['kind'],'clarify'); execute.assert_not_called()
            history,unchanged=store.context('owner',session)
            self.assertEqual(previous,unchanged)
            self.assertTrue(any('base model' in str(message) for message in history))
            # The model completes the pending request with the clarified scope.
            answer=service.ask(store,'owner',session,'Only the base model','auto',self.views,None)
            self.assertEqual(answer['kind'],'table')
            self.assertEqual(answer['table']['rows'],[{'opportunity_no':'0','amount':'10'}])
            fields={f['field'] for f in answer['plan']['filters']}
            self.assertEqual(fields,{'pet_name','stage_group','close_month'})


if __name__=='__main__': unittest.main()

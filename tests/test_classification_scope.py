from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from classification_scope import resolve_classification_scope, definition_guidance
from data_layer import build_canonical_views
from history_store import HistoryStore
from query_engine import QueryExecutor, parse_plan, merge_plan
from query_service import QueryService
from test_supporting_acceptance import line


def plan(value='S(N)'):
    return parse_plan({'filters': [
        {'field': 'seg_3', 'operator': 'in', 'value': value if isinstance(value, list) else [value]},
        {'field': 'stage_group', 'operator': 'eq', 'value': 'Open'},
        {'field': 'subsidiary_subsidiary_code', 'operator': 'eq', 'value': 'SGE'},
        {'field': 'close_month', 'operator': 'between', 'value': ['2026-09-01', '2026-09-30']}],
        'sort': [{'field': 'opportunity_amount', 'direction': 'desc'}], 'limit': 20})


class ClassificationScopeTests(unittest.TestCase):
    def test_conflicting_generation_plans_converge_without_changing_other_intent(self):
        results=[]
        for value in ['S(N)', ['S(N)', 'S(N-1)'], 'FLAGSHIP']:
            original=plan(value)
            resolved=resolve_classification_scope(original, 'show me the top 20 flagship open BOs in SGE in september')
            self.assertEqual(resolved.filters[:-1], original.filters[1:])
            self.assertEqual(resolved.filters[-1].model_dump(), {'field':'seg_1','operator':'eq','value':'FLAGSHIP'})
            self.assertEqual(resolved.sort, original.sort)
            self.assertEqual(resolved.limit, 20)
            self.assertEqual(original.filters[0].field, 'seg_3')
            results.append(resolved)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_missing_model_filter_is_added(self):
        resolved=resolve_classification_scope(parse_plan({}), 'FLAGSHIPS')
        self.assertEqual(resolved.filters[0].field, 'seg_1')

    def test_explicit_generation_definitions(self):
        for text,value in [('current-generation flagship','S(N)'), ('previous generation flagship','S(N-1)')]:
            resolved=resolve_classification_scope(plan(), text)
            self.assertEqual(resolved.filters[-1].field, 'seg_3')
            self.assertEqual(resolved.filters[-1].value, value)
            self.assertEqual(resolved.filters[-1].operator.value, 'eq')

    def test_ambiguous_combinations_do_not_execute(self):
        for text in ['not flagship', 'non-flagship', 'remove flagship filter', 'flagship except current generation',
                     'flagship S(N-2)', 'flagship or tablet', 'latest flagship',
                     'flagship from previous generation', 'flagship segment 3 S(N)',
                     'current-generation flagship and previous-generation flagship']:
            with self.subTest(text=text):
                resolved=resolve_classification_scope(plan(), text)
                self.assertEqual(resolved.result_kind.value, 'clarify')
                self.assertLessEqual(len(resolved.clarification), 300)

    def test_ordinary_followup_keeps_confirmed_scope(self):
        previous=resolve_classification_scope(plan(), 'flagship')
        incoming=parse_plan({'context_action':'refine', 'filters':[{'field':'stage_group','operator':'eq','value':'Won'}]})
        merged=merge_plan(previous,incoming)
        self.assertEqual(resolve_classification_scope(merged,'now Won'),merged)

    def test_named_customer_is_not_silently_filtered_as_a_product_category(self):
        original=parse_plan({'filters':[{'field':'end_customer','operator':'eq','value':'Flagship Trading'}]})
        self.assertEqual(resolve_classification_scope(original,'BOs for Flagship Trading').result_kind.value,'clarify')

    def test_new_bare_scope_replaces_previous_generation_but_keeps_parent_and_product(self):
        original=plan()
        original.filters.extend(parse_plan({'filters':[
            {'field':'biz_group','operator':'eq','value':'SMART'},
            {'field':'pet_name','operator':'eq','value':'Example phone'}]}).filters)
        resolved=resolve_classification_scope(original, 'all flagship products')
        self.assertEqual({f.field for f in resolved.filters},
            {'biz_group','pet_name','seg_1','stage_group','subsidiary_subsidiary_code','close_month'})

    def test_topic_definition_is_used_for_prompt_and_resolution(self):
        self.assertIn('"flagship" means seg_1 eq FLAGSHIP',definition_guidance())
        config={'definitions':[{'term':'premium','field':'seg_2','value':'PREMIUM'}]}
        resolved=resolve_classification_scope(parse_plan({}), 'premium', config)
        self.assertEqual(resolved.filters[0].value,'PREMIUM')

    def test_full_service_includes_older_flagship_excludes_nonflagship_and_keeps_history(self):
        rows=[]
        for i,(seg1,seg3) in enumerate([('FLAGSHIP','S(N)'),('FLAGSHIP','S(N-1)'),('FLAGSHIP','S(N-2)'),('FEATURE','S(N)')]):
            rows.append(dict(line(str(i),'SKU'+str(i),'10','10','1'),seg_1=seg1,seg_3=seg3))
        views=build_canonical_views(rows)
        class Planner:
            def plan(self,*args,**kwargs):
                return parse_plan({'filters':[{'field':'seg_3','operator':'eq','value':'S(N)'}]})
        service=QueryService(Planner(),QueryExecutor())
        with TemporaryDirectory() as home:
            store=HistoryStore(Path(home)/'history.sqlite3'); session=store.create('owner')
            answer=service.ask(store,'owner',session,'show flagship BOs','auto',views,None)
            self.assertEqual(answer['table']['total_rows'],3)
            self.assertEqual({r['opportunity_no'] for r in answer['table']['rows']},{'0','1','2'})
            self.assertTrue(answer['diagnostics']['classification_scope_adjusted'])
            self.assertEqual(answer['returned_plan']['filters'][0]['field'],'seg_3')
            _,previous=store.context('owner',session)
            with patch.object(service,'execute_and_save') as execute:
                answer=service.ask(store,'owner',session,'latest flagship','auto',views,None)
                self.assertEqual(answer['kind'],'clarify')
                execute.assert_not_called()
            self.assertEqual(store.context('owner',session)[1],previous)


if __name__ == '__main__': unittest.main()

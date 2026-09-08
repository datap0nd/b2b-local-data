"""Behavioral regressions from the recorded run, using fictional source rows."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import unittest

from answer_text import money
from history_store import HistoryStore
from query_engine import QueryExecutor, cell_token, parse_plan, result_digest
from reference_evaluator import ReferenceSource, digest_rows, evaluate_supporting
from acceptance_runner import compare_supporting
from data_layer import build_canonical_views
from test_supporting_acceptance import authored_spec, invented_rows, payload


class RecordedFailureRegressions(unittest.TestCase):
    def test_sql_scaled_zero_has_numeric_digest_and_still_detects_changes(self):
        records=invented_rows()
        records[0].update(quantity='0.0000000000', probability='0.0000000000')
        spec=authored_spec()
        expected=evaluate_supporting(ReferenceSource(records),spec)
        actual=payload(records,spec)
        self.assertEqual(Decimal(actual['supporting']['views']['detail']['rows'][0]['quantity']),0)
        self.assertTrue(compare_supporting(expected,actual)['ok'])
        for value in (Decimal('0E-10'),'0E-10','0.0000000000',0):
            self.assertEqual(cell_token(value,'number'),'n:0')
            self.assertEqual(result_digest([{'quantity':value}],['quantity']),digest_rows([{'quantity':Decimal(0)}],['quantity']))
        self.assertNotEqual(cell_token('0001','text'),cell_token(1,'number'))
        broken=deepcopy(actual)
        broken['supporting']['views']['detail']['rows'][0]['quantity']='1'
        self.assertFalse(compare_supporting(expected,broken)['ok'])

    def test_complete_date_groups_survive_query_and_saved_history(self):
        base=invented_rows()[0]
        records=[dict(base,opportunity_no=f'O{i:04}',close_date=(date(2023,1,1)+timedelta(days=i)).isoformat()) for i in range(1011)]
        views=build_canonical_views(records)
        plan=parse_plan({'result_kind':'aggregate','presentation':'chart','grain':'opportunity','group_by':['close_date'],'measures':['opportunity_count'],'chart_type':'line'})
        executor=QueryExecutor()
        table=executor.execute(views,plan)
        self.assertEqual(len(table['rows']),1011)
        self.assertFalse(table['truncated'])
        self.assertEqual(table['rows'][-1]['close_date'],records[-1]['close_date'])
        self.assertEqual(len(HistoryStore.bounded(table)['rows']),1011)
        limited=executor.execute(views,plan.model_copy(update={'limit':10}))
        self.assertEqual(len(limited['rows']),10)
        self.assertTrue(limited['truncated'])
        rows=executor.execute(views,parse_plan({'result_kind':'rows','grain':'opportunity'}))
        self.assertEqual(len(rows['rows']),1000)
        self.assertTrue(rows['truncated'])

    def test_quantity_display_groups_digits_without_rounding(self):
        self.assertEqual(money('35428771.0000000000',decimals=None),'35,428,771')
        self.assertEqual(money('1234.00100',decimals=None),'1,234.001')
        self.assertEqual(money('0E-10',decimals=None),'0')

    def test_explicit_date_fields_select_different_populations(self):
        records=invented_rows()
        records[0].update(close_date='31/12/2025',close_month='1/1/2026')
        views=build_canonical_views(records)
        executor=QueryExecutor()
        def selected(field):
            plan=parse_plan({'grain':'opportunity_sku','filters':[{'field':field,'operator':'between','value':['2026-01-01','2026-12-31']}]})
            return {(row['opportunity_no'],row['product_code']) for row in executor.execute(views,plan)['rows']}
        self.assertNotIn(('001','X'),selected('close_date'))
        self.assertIn(('001','X'),selected('close_month'))


if __name__=='__main__': unittest.main()

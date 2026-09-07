from datetime import date
from decimal import Decimal
import unittest

from data_layer import build_canonical_views, clean_date, clean_number, demo_rows


class DataGrainTests(unittest.TestCase):
    def test_one_row_per_grain_and_amount_alignment(self):
        views=build_canonical_views(demo_rows())
        self.assertEqual(len(views.sku),4)
        self.assertEqual(len(views.opportunity),3)
        self.assertFalse(views.sku.duplicated(['opportunity_no','product_code']).any())
        self.assertFalse(views.opportunity.duplicated('opportunity_no').any())
        for row in views.opportunity.to_dict('records'):
            children=views.sku[views.sku.opportunity_no==row['opportunity_no']]
            self.assertEqual(row['opportunity_amount'],sum(children.sku_amount))
        first=views.opportunity.iloc[0]
        self.assertEqual(first.opportunity_amount,Decimal(750))
        self.assertEqual(first.quantity,Decimal(4))
        self.assertEqual(first.product_codes,'SKU-A, SKU-B')
        self.assertEqual(first.source_row_count,3)
        self.assertEqual(first.sku_count,2)

    def test_duplicate_metadata_warns_both_grains_without_dropping_results(self):
        rows=demo_rows();rows[0]['opportunity_owner']='Zoe'
        views=build_canonical_views(rows)
        self.assertTrue(views.sku.iloc[0].has_quality_warning)
        self.assertTrue(views.opportunity.iloc[0].has_quality_warning)
        self.assertEqual(views.sku.iloc[0].opportunity_owner,'Alex')

    def test_parent_amount_discrepancy_exact_cent_tolerance(self):
        for parent,expected in [('749.99',False),('750.01',False),('749.989',True),('750.011',True)]:
            with self.subTest(parent=parent):
                rows=demo_rows()[:3]
                for row in rows:row['opp_amount_converted']=parent
                self.assertEqual(build_canonical_views(rows).opportunity.iloc[0].has_amount_discrepancy,expected)

    def test_parent_min_max_conflict_and_missing_parent_warn(self):
        rows=demo_rows()[:3];rows[0]['opp_amount_converted']='751'
        views=build_canonical_views(rows)
        self.assertEqual(views.sku.iloc[0].exported_opp_amount_value_count,2)
        self.assertTrue(views.opportunity.iloc[0].has_amount_discrepancy)
        for row in rows: row['opp_amount_converted']=None
        self.assertTrue(build_canonical_views(rows).opportunity.iloc[0].has_amount_discrepancy)

    def test_numeric_and_probability_normalization(self):
        self.assertEqual(clean_number(' 75% ',True),Decimal('.75'))
        self.assertEqual(clean_number('75',True),Decimal('.75'))
        self.assertEqual(clean_number(' -10.25 '),Decimal('-10.25'))
        for value in ['1,000','1e3','NaN','Infinity','.5','5.','',None]:
            self.assertIsNone(clean_number(value))

    def test_sql_sum_null_semantics(self):
        rows=demo_rows()[:2];rows[0]['amount_converted']='invalid'
        self.assertEqual(build_canonical_views(rows).sku.iloc[0].sku_amount,Decimal(200))
        rows[1]['amount_converted']=None
        self.assertIsNone(build_canonical_views(rows).sku.iloc[0].sku_amount)

    def test_dates_are_valid_calendar_dates(self):
        self.assertEqual(clean_date('29/02/2024'),date(2024,2,29))
        for value in ['29/02/2025','31/04/2026','01/13/2026','01/01/0000','2026-01-01','bad','1/1/2026']:
            self.assertIsNone(clean_date(value))

    def test_blank_business_keys_are_excluded(self):
        rows=demo_rows();rows[0]['opportunity_no']=' ';rows[1]['product_code']=None
        views=build_canonical_views(rows)
        self.assertEqual(views.excluded_rows,2)
        self.assertEqual(views.sku.source_row_count.sum(),3)

    def test_null_metadata_does_not_count_as_distinct_value(self):
        rows=demo_rows()[:2];rows[0]['end_customer']=None
        sku=build_canonical_views(rows).sku.iloc[0]
        self.assertFalse(sku.has_quality_warning)
        self.assertEqual(sku.end_customer,'Example North')

    def test_empty_source_keeps_schema(self):
        views=build_canonical_views([])
        self.assertTrue(views.sku.empty)
        self.assertIn('opportunity_amount',views.opportunity.columns)

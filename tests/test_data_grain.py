from datetime import date
from decimal import Decimal
import unittest

from app_config import AppError
from data_layer import (OPPORTUNITY_COLUMNS, RAW_COLUMNS, SKU_COLUMNS, SOURCE_FIELDS, SQL_COLUMNS, build_canonical_views, clean_date,
                        clean_number, demo_rows, resolve_columns)

# Salesforce-style export headers for every canonical field, in the export's own spelling.
EXPORT_HEADERS = {'opportunity_no':'Opportunity No.','product_code':'Product Code','subsidiary_subsidiary_code':'Subsidiary: Subsidiary Code',
    'opportunity_name':'Opportunity Name','end_customer':'End Customer','gscm_product_group_new':'GSCM Product Group (New)','pet_name':'PET Name',
    'stage':'Stage','opportunity_owner':'Opportunity Owner','biz_focus':'Biz Focus','business_location':'Business Location','division':'Division',
    'sales_type_detail':'Sales Type Detail','type':'Type','amount_converted_currency':'Amount (converted) Currency',
    'opp_amount_converted_currency':'Opportunity Amount (converted) Currency','rollout_period_to':'Rollout Period To','rollout_period_from':'Rollout Period From',
    'first_channel':'1st Channel','comment':'Comment','quantity':'Quantity','amount_converted':'Amount (converted)','opp_amount_converted':'Opportunity Amount (converted)',
    'probability':'Probability (%)','age':'Age','deal_size_on_pricing_date_usd':'Deal Size on Pricing Date (USD)','close_month':'Close Month','close_date':'Close Date',
    'created_date':'Created Date','last_modified_date':'Last Modified Date'}


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
        self.assertEqual(clean_number('1234567890.123456789'),Decimal('1234567890.123456789'))
        for value in ['1,000','1e3','NaN','Infinity','.5','5.','',None]:
            self.assertIsNone(clean_number(value))

    def test_sql_sum_null_semantics(self):
        rows=demo_rows()[:2];rows[0]['amount_converted']='invalid'
        self.assertEqual(build_canonical_views(rows).sku.iloc[0].sku_amount,Decimal(200))
        rows[1]['amount_converted']=None
        self.assertIsNone(build_canonical_views(rows).sku.iloc[0].sku_amount)

    def test_dates_are_valid_day_first_calendar_dates(self):
        self.assertEqual(clean_date('29/02/2024'),date(2024,2,29))
        self.assertEqual(clean_date('1/1/2026'),date(2026,1,1))
        self.assertEqual(clean_date(' 9/10/2026 '),date(2026,10,9))
        self.assertEqual(clean_date('09/1/2026'),date(2026,1,9))
        self.assertEqual(clean_date('2026-01-01'),date(2026,1,1));self.assertEqual(clean_date('2026-01-01 00:00:00'),date(2026,1,1))   # ISO text from typed database columns
        for value in ['29/02/2025','31/04/2026','01/13/2026','01/01/0000','2026-13-01','bad','1/1/26','0/1/2026','1/0/2026','', None]:
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
        self.assertIn('deal_size_on_pricing_date_usd',views.opportunity.columns)

    def test_all_thirty_columns_are_mapped_once(self):
        self.assertEqual(len(SOURCE_FIELDS),30)
        self.assertEqual(len(set(RAW_COLUMNS)),30)
        self.assertEqual(len(set(SQL_COLUMNS.values())),30)
        self.assertEqual(SQL_COLUMNS['first_channel'],'1st_channel')
        for name in ('age','comment','deal_size_on_pricing_date_usd'):
            self.assertEqual(SQL_COLUMNS[name],name)
        for name in ('first_channel','age','comment','deal_size_on_pricing_date_usd'):
            self.assertIn(name,SKU_COLUMNS);self.assertIn(name,OPPORTUNITY_COLUMNS)
        # Every canonical name and every SQL column name resolves to itself.
        self.assertEqual(resolve_columns(RAW_COLUMNS),{name:name for name in RAW_COLUMNS})
        self.assertEqual(resolve_columns(SQL_COLUMNS.values()),SQL_COLUMNS)

    def test_export_headers_resolve_including_quoted_first_channel(self):
        headers=[EXPORT_HEADERS[name] for name in RAW_COLUMNS]+['Unused Extra Column']
        self.assertEqual(resolve_columns(headers),EXPORT_HEADERS)
        for header in ('"1st_channel"','1st channel','1ST_CHANNEL',' 1st Channel '):
            names=[SQL_COLUMNS[name] for name in RAW_COLUMNS if name!='first_channel']+[header.strip('"')]
            self.assertEqual(resolve_columns(names)['first_channel'],header.strip('"'))

    def test_missing_and_ambiguous_columns_are_reported(self):
        with self.assertRaises(AppError) as missing:
            resolve_columns([name for name in RAW_COLUMNS if name not in ('first_channel','age')])
        self.assertIn('first_channel (1st_channel)',str(missing.exception));self.assertIn('age',str(missing.exception))
        with self.assertRaises(AppError) as ambiguous:
            resolve_columns(RAW_COLUMNS+['1st Channel'])
        self.assertIn('first_channel',str(ambiguous.exception));self.assertIn('1st Channel',str(ambiguous.exception))

    def test_identifiers_are_preserved_as_text(self):
        rows=demo_rows()[:1];rows[0].update(opportunity_no='000123',product_code='1E3',subsidiary_subsidiary_code='007',comment=' 12345 ')
        sku=build_canonical_views(rows).sku.iloc[0]
        self.assertEqual((sku.opportunity_no,sku.product_code,sku.subsidiary_subsidiary_code,sku.comment),('000123','1E3','007','12345'))

    def test_added_attributes_are_selected_not_summed(self):
        views=build_canonical_views(demo_rows())
        first=views.opportunity.iloc[0]
        self.assertEqual((first.first_channel,first.age,first.comment,first.deal_size_on_pricing_date_usd),('Partner',Decimal(30),'Fictional note',Decimal(750)))
        self.assertEqual(views.sku.iloc[0].age,Decimal(30))
        self.assertEqual(views.sku.iloc[0].deal_size_on_pricing_date_usd,Decimal(750))
        self.assertFalse(views.opportunity.iloc[0].has_quality_warning)

    def test_invalid_attribute_values_become_null(self):
        rows=demo_rows()[:1];rows[0].update(age='30 days',deal_size_on_pricing_date_usd='$1,000',first_channel='',comment='   ')
        row=build_canonical_views(rows).opportunity.iloc[0]
        self.assertIsNone(row.age);self.assertIsNone(row.deal_size_on_pricing_date_usd);self.assertIsNone(row.first_channel);self.assertIsNone(row.comment)

    def test_duplicate_sku_rows_keep_one_attribute_value(self):
        views=build_canonical_views(demo_rows()[:2])
        self.assertEqual(len(views.sku),1)
        self.assertEqual(views.sku.iloc[0].deal_size_on_pricing_date_usd,Decimal(750))
        self.assertEqual(views.opportunity.iloc[0].deal_size_on_pricing_date_usd,Decimal(750))

    def test_conflicting_attributes_are_flagged_at_both_grains(self):
        rows=demo_rows()[:3];rows[1]['age']='31'
        views=build_canonical_views(rows)
        self.assertTrue(views.sku.iloc[0].has_quality_warning);self.assertEqual(views.sku.iloc[0].age,Decimal(30))
        self.assertTrue(views.opportunity.iloc[0].has_quality_warning)
        rows=demo_rows()[:3];rows[2]['deal_size_on_pricing_date_usd']='800'
        views=build_canonical_views(rows)
        self.assertFalse(views.sku.has_quality_warning.any())
        self.assertTrue(views.opportunity.iloc[0].has_quality_warning)
        self.assertEqual(views.opportunity.iloc[0].deal_size_on_pricing_date_usd,Decimal(750))

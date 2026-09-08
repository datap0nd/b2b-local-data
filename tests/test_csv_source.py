"""Local CSV exports go through the same parser and grain rules as the raw PostgreSQL table."""
import csv
from decimal import Decimal
import os
from pathlib import Path
import sys
import tempfile
import unittest

from app_config import AppError,Settings
from data_layer import RAW_COLUMNS,SQL_COLUMNS,DataRepository,build_canonical_views,demo_rows,read_csv_source

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_data_grain import EXPORT_HEADERS


def write_export(path,rows,headers=None,encoding='utf-8-sig',quote_first_channel=True):
    """Write rows with export-style headers; the 1st Channel header is quoted the way exports quote it."""
    headers=headers or (SQL_COLUMNS | EXPORT_HEADERS)
    with Path(path).open('w',encoding=encoding,newline='') as stream:
        stream.write(','.join('"'+headers[name]+'"' if quote_first_channel and name=='first_channel' else headers[name] for name in RAW_COLUMNS)+'\r\n')
        writer=csv.writer(stream)
        for row in rows:writer.writerow(['' if row.get(name) is None else row[name] for name in RAW_COLUMNS])


def fixture_rows():
    rows=demo_rows()
    rows[0]['comment']='Quoted, with comma and "quotes"\nand a second line'
    rows[2]['close_date']='1/10/2026';rows[3].update(opportunity_name='  Padded  ',age='');rows[4]['deal_size_on_pricing_date_usd']='n/a'
    rows.append(dict(rows[0],opportunity_no='00042',product_code='0007',subsidiary_subsidiary_code='010',amount_converted='10.50',opp_amount_converted='10.50',deal_size_on_pricing_date_usd='10.50',quantity='1'))
    rows.append(dict(rows[0],opportunity_no='',product_code='SKU-Z'))
    return rows


class CsvSourceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def settings(self,**values):return Settings(self.home,{'DB_KIND':'csv','B2B_CSV_PATH':'exports/salesforce.csv','MAX_SOURCE_ROWS':'100000'}|values)
    def export(self,rows=None,**kwargs):
        path=self.home/'exports/salesforce.csv';path.parent.mkdir(exist_ok=True)
        write_export(path,fixture_rows() if rows is None else rows,**kwargs);return path
    def test_relative_path_resolves_from_configuration_folder(self):
        self.export();settings=self.settings()
        self.assertEqual(settings.csv_path,(self.home/'exports/salesforce.csv').resolve())
        self.assertEqual(settings.source_label,'CSV file salesforce.csv')
        views=DataRepository(settings).load()
        self.assertEqual((views.source,views.source_name),('csv','salesforce.csv'))
        absolute=DataRepository(self.settings(B2B_CSV_PATH=str(self.home/'exports/salesforce.csv'))).load()
        self.assertEqual(absolute.opportunity.to_dict('records'),views.opportunity.to_dict('records'))
    def test_csv_matches_shared_parser_on_identical_records(self):
        self.export();views=DataRepository(self.settings()).load();expected=build_canonical_views(fixture_rows())
        for name in ('sku','opportunity'):
            self.assertEqual(getattr(views,name).to_dict('records'),getattr(expected,name).to_dict('records'))
        self.assertEqual(views.excluded_rows,1)
        self.assertEqual(len(views.opportunity),4);self.assertEqual(len(views.sku),5)
        by_key=views.sku.set_index(['opportunity_no','product_code'])
        self.assertEqual(by_key.loc[('00042','0007')].subsidiary_subsidiary_code,'010')
        self.assertEqual(by_key.loc[('00042','0007')].sku_amount,Decimal('10.50'))
        first=views.opportunity.set_index('opportunity_no').loc['OPP-001']
        self.assertEqual(first.opportunity_amount,Decimal(750));self.assertEqual(first.deal_size_on_pricing_date_usd,Decimal(750))
        self.assertEqual(views.opportunity.set_index('opportunity_no').loc['00042'].comment,'Quoted, with comma and "quotes"\nand a second line')
        self.assertEqual(first.close_date.isoformat(),'2026-10-01');self.assertEqual(by_key.loc[('OPP-001','SKU-A')].close_date.isoformat(),'2026-10-15')
        self.assertIsNone(views.opportunity.set_index('opportunity_no').loc['OPP-003'].deal_size_on_pricing_date_usd)
        self.assertEqual(views.opportunity.set_index('opportunity_no').loc['OPP-002'].opportunity_name,'Padded')
    def test_sql_column_names_and_unquoted_headers_are_accepted(self):
        for headers in (SQL_COLUMNS,{name:name for name in RAW_COLUMNS}):
            path=self.export(headers=headers,quote_first_channel=False)
            self.assertEqual(len(read_csv_source(path)),len(fixture_rows()))
    def test_every_value_stays_text_until_parsed(self):
        raw=read_csv_source(self.export())
        self.assertEqual(list(raw.columns),RAW_COLUMNS)
        self.assertTrue(all(isinstance(value,str) for value in raw.opportunity_no))
        self.assertIn('00042',set(raw.opportunity_no));self.assertIn('0007',set(raw.product_code))
        self.assertEqual(set(raw.age),{'30','45',''})
    def test_missing_malformed_and_wrong_files_report_clearly(self):
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('does not exist',str(error.exception));self.assertIn('B2B_CSV_PATH',str(error.exception))
        path=self.export()
        with path.open('a',encoding='utf-8',newline='') as stream:stream.write('OPP-9,SKU-9,extra,'+','.join(['x']*len(RAW_COLUMNS))+'\n')
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('malformed',str(error.exception))
        path.write_text('',encoding='utf-8')
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('no header row',str(error.exception))
        path.write_text('only,three,columns\n1,2,3\n',encoding='utf-8')
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('missing required Salesforce columns',str(error.exception));self.assertIn('first_channel (1st_channel)',str(error.exception))
        path.write_text(','.join(RAW_COLUMNS)+',1st Channel\n',encoding='utf-8')
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('ambiguous',str(error.exception))
        self.export(encoding='utf-16')
        with self.assertRaises(AppError) as error:DataRepository(self.settings()).load()
        self.assertIn('B2B_CSV_ENCODING',str(error.exception))
        self.assertEqual(len(DataRepository(self.settings(B2B_CSV_ENCODING='utf-16')).load().sku),5)
        with self.assertRaises(AppError):DataRepository(self.settings(B2B_CSV_ENCODING='no-such-codec')).load()
        with self.assertRaises(AppError):Settings(self.home,{'DB_KIND':'csv'}).validate()
    def test_row_cap_applies_to_csv_too(self):
        self.export()
        with self.assertRaises(AppError) as error:DataRepository(self.settings(MAX_SOURCE_ROWS='3')).load()
        self.assertIn('exceeds 3 rows',str(error.exception))
    def test_blank_lines_and_missing_trailing_fields_become_null(self):
        path=self.export(fixture_rows()[:1])
        with path.open('a',encoding='utf-8',newline='') as stream:stream.write('\r\nOPP-7,SKU-7\r\n')
        views=DataRepository(self.settings()).load()
        row=views.opportunity.set_index('opportunity_no').loc['OPP-7']
        self.assertIsNone(row.stage);self.assertIsNone(row.opportunity_amount);self.assertTrue(row.has_amount_discrepancy)


@unittest.skipUnless(os.environ.get('B2B_SAMPLE_CSV_PATH'),'Opt-in check against the supplied sample export')
class SuppliedSampleTests(unittest.TestCase):
    """Runs only on a machine holding the supplied export; the file stays local and Git-ignored."""
    def test_supplied_sample_totals(self):
        path=Path(os.environ['B2B_SAMPLE_CSV_PATH'])
        raw=read_csv_source(path,os.environ.get('B2B_SAMPLE_CSV_ENCODING','utf-8-sig'))
        self.assertEqual(len(raw),307)
        views=DataRepository(Settings(path.parent,{'DB_KIND':'csv','B2B_CSV_PATH':path.name,'B2B_CSV_ENCODING':os.environ.get('B2B_SAMPLE_CSV_ENCODING','utf-8-sig')})).load()
        self.assertEqual(len(views.opportunity),112)
        self.assertEqual(len(views.sku),305)
        self.assertEqual(int(views.sku.source_row_count.sum())+views.excluded_rows,307)
        self.assertFalse(views.sku.duplicated(['opportunity_no','product_code']).any())

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

import pandas as pd
from sqlalchemy.exc import DBAPIError

from app_config import AppError,Settings
from data_layer import RAW_COLUMNS,SQL_COLUMNS,DataRepository,build_canonical_views,demo_rows
from ui_app import Snapshots


def database_error(code):return DBAPIError('hidden',None,Exception({'C':code}),False)


class GatewayTests(unittest.TestCase):
    def repository(self,columns=None,**extra):
        settings=Settings(Path('.'),{'DB_KIND':'postgres','MAX_SOURCE_ROWS':'100000'}|extra)
        connection=MagicMock();connection.__enter__.return_value=connection
        columns=list(SQL_COLUMNS.values()) if columns is None else columns
        connection.execute.return_value.fetchall.return_value=[(name,) for name in columns]
        engine=MagicMock();engine.connect.return_value=connection
        return DataRepository(settings,engine),connection
    def statements(self,connection):return [str(call.args[0]) for call in connection.execute.call_args_list]
    def test_raw_table_is_read_once_in_a_read_only_transaction(self):
        repo,connection=self.repository()
        with patch.object(repo,'_read',return_value=pd.DataFrame(demo_rows(),dtype=object)) as read:
            views=repo.load()
        self.assertEqual(views.source,'postgres');self.assertEqual(views.source_name,'bi_reporting.b2b_project')
        self.assertEqual(read.call_count,1);self.assertEqual(read.call_args.args[2]['first_channel'],'1st_channel')
        self.assertEqual(len(views.opportunity),3)
        statements=self.statements(connection)
        self.assertIn('SET TRANSACTION READ ONLY',statements)
        self.assertTrue(any('statement_timeout' in s for s in statements))
        self.assertTrue(any('information_schema.columns' in s for s in statements))
        self.assertFalse(any('_v' in s or 'schema_version' in s for s in statements))
    def test_select_quotes_and_aliases_every_column(self):
        repo,connection=self.repository()
        connection.execute.return_value.fetchall.side_effect=[[(name,) for name in SQL_COLUMNS.values()],[]]
        views=repo.load()
        select=self.statements(connection)[-1]
        self.assertIn('"1st_channel" AS "first_channel"',select);self.assertIn('"deal_size_on_pricing_date_usd" AS "deal_size_on_pricing_date_usd"',select)
        self.assertIn('FROM "bi_reporting"."b2b_project" LIMIT :cap',select);self.assertEqual(select.count(' AS '),30)
        self.assertTrue(views.opportunity.empty)
    def test_missing_source_columns_are_reported_before_reading(self):
        repo,connection=self.repository([c for c in SQL_COLUMNS.values() if c not in ('1st_channel','comment')])
        with patch.object(repo,'_read') as read,self.assertRaises(AppError) as error:repo.load()
        read.assert_not_called();self.assertIn('first_channel (1st_channel)',str(error.exception));self.assertIn('comment',str(error.exception))
        repo,connection=self.repository([])
        with self.assertRaises(AppError) as error:repo.load()
        self.assertIn('not readable',str(error.exception))
    def test_row_cap_is_enforced(self):
        repo,connection=self.repository(MAX_SOURCE_ROWS='2')
        rows=[tuple(row[name] for name in RAW_COLUMNS) for row in demo_rows()[:3]]
        connection.execute.return_value.fetchall.side_effect=[[(name,) for name in SQL_COLUMNS.values()],rows]
        with self.assertRaises(AppError) as error:repo.load()
        self.assertIn('exceeds 2 rows',str(error.exception))
    def test_sql_failure_never_falls_back_to_csv_or_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            csv=Path(temp)/'export.csv';csv.write_text(','.join(RAW_COLUMNS)+'\n')
            for code in ('42501','42P01','08006'):
                repo,connection=self.repository(B2B_CSV_PATH=str(csv))
                with patch.object(repo,'_read',side_effect=database_error(code)),patch('data_layer.read_csv_source') as read_csv,self.assertRaises(AppError) as error:repo.load()
                read_csv.assert_not_called();self.assertIn('PostgreSQL read failed',str(error.exception))
    def test_snapshot_reuse_refresh_and_failure(self):
        repository=MagicMock();repository.load.side_effect=['first','second',AppError('offline'),'fourth']
        cache=Snapshots(repository,60)
        self.assertEqual(cache.get()[0],'first');self.assertEqual(cache.get()[0],'first')
        self.assertEqual(repository.load.call_count,1)
        self.assertEqual(cache.get(True)[0],'second')
        with self.assertRaises(AppError):cache.get(True)
        self.assertEqual(cache.get()[0],'fourth')

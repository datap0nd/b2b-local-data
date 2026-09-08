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
        self.assertEqual(views.source,'postgres');self.assertEqual(views.source_name,'bi_reporting.b2b_project_segmented')
        self.assertEqual(read.call_count,1);self.assertEqual(read.call_args.args[2]['first_channel'],'1st_channel')
        self.assertEqual(len(views.opportunity),3)
        statements=self.statements(connection)
        self.assertIn('SET TRANSACTION READ ONLY',statements)
        self.assertTrue(any('statement_timeout' in s for s in statements))
        self.assertTrue(any('pg_catalog.pg_attribute' in s for s in statements))
        self.assertFalse(any('_v' in s or 'schema_version' in s for s in statements))
    def test_select_quotes_and_aliases_every_column(self):
        repo,connection=self.repository()
        connection.execute.return_value.fetchall.side_effect=[[(name,) for name in SQL_COLUMNS.values()],[]]
        views=repo.load()
        select=next(s for s in self.statements(connection) if 'LIMIT :cap' in s)
        self.assertIn('CAST("1st_channel" AS text) AS "first_channel"',select);self.assertIn('CAST("deal_size_on_pricing_date_usd" AS text) AS "deal_size_on_pricing_date_usd"',select)
        self.assertIn('FROM "bi_reporting"."b2b_project_segmented" LIMIT :cap',select);self.assertEqual(select.count('CAST('),35);self.assertEqual(select.count(') AS "'),35)
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
    def test_failure_message_carries_the_driver_diagnosis_without_the_password(self):
        repo,connection=self.repository(RO_SQL_PW='s3cret')
        with patch.object(repo,'_read',side_effect=DBAPIError('hidden',None,Exception({'S':'FATAL','C':'28P01','M':'password authentication failed for user "reader" s3cret'}),False)),self.assertRaises(AppError) as error:repo.load()
        self.assertIn('28P01',str(error.exception));self.assertIn('password authentication failed',str(error.exception));self.assertNotIn('s3cret',str(error.exception))
        self.assertIn('RO_SQL_USER/RO_SQL_PW',str(error.exception))
        with patch.object(repo,'_read',side_effect=DBAPIError('hidden',None,Exception('Server refuses SSL'),False)),self.assertRaises(AppError) as error:repo.load()
        self.assertIn('set DB_SSL=prefer or DB_SSL=false',str(error.exception))
    def test_prefer_mode_falls_back_to_plain_after_a_tls_failure(self):
        import ssl as ssl_module
        settings=Settings(Path('.'),{'DB_KIND':'postgres','PGURL':'db.example:5432/postgres','DB_SSL':'prefer'})
        repo=DataRepository(settings);contexts=[]
        tls_engine=MagicMock();tls_engine.connect.side_effect=ssl_module.SSLError('handshake failure');plain_engine=MagicMock()
        def build(context):contexts.append(context);return tls_engine if context else plain_engine
        with patch.object(repo,'_build_engine',side_effect=build):self.assertIs(repo._engine(),plain_engine)
        self.assertEqual(len(contexts),2);self.assertEqual(contexts[0].verify_mode,ssl_module.CERT_NONE);self.assertFalse(contexts[0].check_hostname);self.assertIs(contexts[1],False)
        tls_engine.dispose.assert_called_once()
        other=DataRepository(settings);failing=MagicMock();failing.connect.side_effect=RuntimeError('password authentication failed')
        with patch.object(other,'_build_engine',return_value=failing),self.assertRaises(RuntimeError):other._engine()
    def test_snapshot_reuse_refresh_and_failure(self):
        repository=MagicMock();repository.load.side_effect=['first','second',AppError('offline'),'fourth']
        cache=Snapshots(repository,60)
        self.assertEqual(cache.get()[0],'first');self.assertEqual(cache.get()[0],'first')
        self.assertEqual(repository.load.call_count,1)
        self.assertEqual(cache.get(True)[0],'second')
        with self.assertRaises(AppError):cache.get(True)
        self.assertEqual(cache.get()[0],'fourth')

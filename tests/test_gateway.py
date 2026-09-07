from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch

import pandas as pd
from sqlalchemy.exc import DBAPIError

from app_config import AppError,Settings
from data_layer import DataRepository,build_canonical_views,demo_rows
from ui_app import Snapshots


def database_error(code):return DBAPIError('hidden',None,Exception({'C':code}),False)


class GatewayTests(unittest.TestCase):
    def repository(self):
        settings=Settings(Path('.'),{'DB_KIND':'postgres','MAX_SOURCE_ROWS':'100000'})
        connection=MagicMock();connection.__enter__.return_value=connection
        connection.execute.return_value.scalar.return_value=1
        engine=MagicMock();engine.connect.return_value=connection
        return DataRepository(settings,engine),connection
    def test_database_views_preferred(self):
        repo,connection=self.repository();expected=build_canonical_views(demo_rows())
        with patch.object(repo,'_read',side_effect=[expected.sku,expected.opportunity]) as read:
            views=repo.load()
        self.assertEqual(views.source,'database_views');self.assertEqual(read.call_count,2)
        self.assertIn('SET TRANSACTION READ ONLY',[str(call.args[0]) for call in connection.execute.call_args_list])
    def test_denied_or_missing_views_fall_back_after_savepoint(self):
        for code in ('42501','42P01'):
            repo,connection=self.repository()
            with patch.object(repo,'_read',side_effect=[database_error(code),pd.DataFrame(demo_rows())]) as read:
                views=repo.load()
            self.assertEqual(len(views.opportunity),3)
            self.assertTrue(views.fallback_reason)
            self.assertTrue(connection.begin_nested.return_value.__exit__.called)
    def test_schema_mismatch_or_connection_failure_does_not_fall_back(self):
        repo,connection=self.repository();connection.execute.return_value.scalar.return_value=2
        with patch.object(repo,'_read') as read,self.assertRaises(AppError):repo.load()
        read.assert_not_called()
        repo,connection=self.repository()
        with patch.object(repo,'_read',side_effect=database_error('08006')) as read,self.assertRaises(AppError):repo.load()
        self.assertEqual(read.call_count,1)
    def test_snapshot_reuse_refresh_and_failure(self):
        repository=MagicMock();repository.load.side_effect=['first','second',AppError('offline'),'fourth']
        cache=Snapshots(repository,60)
        self.assertEqual(cache.get()[0],'first');self.assertEqual(cache.get()[0],'first')
        self.assertEqual(repository.load.call_count,1)
        self.assertEqual(cache.get(True)[0],'second')
        with self.assertRaises(AppError):cache.get(True)
        self.assertEqual(cache.get()[0],'fourth')

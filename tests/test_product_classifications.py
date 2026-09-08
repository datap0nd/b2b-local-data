"""Fictional classification behavior, not qualification of the live segmented view."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app_config import AppError, ROOT, Settings
from data_layer import CLASSIFICATION_FIELDS, RAW_COLUMNS, DataRepository, build_canonical_views, dataset_fingerprint, demo_rows, read_csv_source
from query_engine import PlannerClient, PlanRejected, QueryExecutor, merge_plan, parse_plan
from reference_evaluator import ReferenceSource, fingerprint
from scripts.install_config import migrate, migrate_segmented_source, restore


def fixture():
    rows = demo_rows()
    for row in rows:
        smart = row['product_code'] == 'SKU-A'
        row.update(biz_group='SMART' if smart else 'ACCESSORY', seg_1='FLAGSHIP' if smart else 'ACCESSORY',
                   seg_2='S' if smart else 'ENTRY', seg_3='S(N)' if smart else 'S(N-1)', series='A SERIES CASE' if smart else 'A0x')
    return rows


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.rows = fixture(); self.views = build_canonical_views(self.rows)
    def run_plan(self, **values):
        return QueryExecutor().execute(self.views, parse_plan(values))
    def test_every_level_supports_grouping_and_row_columns(self):
        for field in CLASSIFICATION_FIELDS:
            with self.subTest(field=field):
                result = self.run_plan(intent='metric', grain='opportunity_sku', dimensions=[field], measures=['quantity'])
                self.assertEqual(sum(int(r['quantity']) for r in result['rows']), 9)
                detail = self.run_plan(grain='opportunity_sku', dimensions=[field])
                self.assertIn(field, detail['columns'])
                self.assertNotIn(field, self.views.opportunity.columns)
                self.assertIn(field, ReferenceSource(self.rows).sku[0])
    def test_smart_matching_products_and_whole_opportunities_have_different_scope(self):
        filters = [{'field':'biz_group', 'operator':'eq', 'value':'smart'}]
        whole = self.run_plan(filters=filters)
        detail = self.run_plan(grain='opportunity_sku', filters=filters)
        self.assertEqual(whole['rows'][0]['opportunity_amount'], '750')
        self.assertEqual(detail['rows'][0]['sku_amount'], '600')
        self.assertEqual(whole['rows'][0]['quantity'], '4')
        self.assertEqual(detail['rows'][0]['quantity'], '3')
    def test_generation_labels_are_literal_and_case_insensitive(self):
        for value, count in [('s(n)',1), ('S(N-1)',3), ('S(N-2)',0)]:
            result = self.run_plan(grain='opportunity_sku', filters=[{'field':'seg_3','operator':'eq','value':value}])
            self.assertEqual(result['total_rows'], count)
    def test_followup_replaces_generation_and_keeps_parent_filter(self):
        prior = parse_plan({'grain':'opportunity_sku','filters':[{'field':'biz_group','operator':'eq','value':'SMART'}, {'field':'seg_3','operator':'eq','value':'S(N)'}]})
        next_plan = merge_plan(prior, parse_plan({'context_action':'refine','filters':[{'field':'seg_3','operator':'eq','value':'S(N-1)'}]}))
        self.assertEqual({f.field:f.value for f in next_plan.filters}, {'biz_group':'SMART','seg_3':'S(N-1)'})
    def test_classifications_cannot_repeat_opportunity_deal_size(self):
        for field in CLASSIFICATION_FIELDS:
            with self.assertRaises(PlanRejected):
                self.run_plan(intent='metric',grain='opportunity_sku',dimensions=[field],measures=['deal_size'])
    def test_fingerprint_changes_with_classification_and_matches_reference(self):
        before = dataset_fingerprint(self.rows)
        self.assertEqual(before, fingerprint(self.rows))
        self.rows[0]['series'] = 'Changed classification'
        self.assertNotEqual(before, dataset_fingerprint(self.rows))
        self.assertEqual(dataset_fingerprint(self.rows), fingerprint(self.rows))
    def test_legacy_csv_has_unknown_classifications_not_fabricated_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.csv'
            fields = [f for f in RAW_COLUMNS if f not in CLASSIFICATION_FIELDS]
            with path.open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fields,extrasaction='ignore'); writer.writeheader(); writer.writerows(self.rows)
            raw = read_csv_source(path)
            self.assertTrue(raw[list(CLASSIFICATION_FIELDS)].isna().all().all())
    def test_materialized_view_catalog_query_and_missing_classifications(self):
        connection = Mock(); connection.execute.return_value.fetchall.return_value = [(f,) for f in RAW_COLUMNS]
        repository = DataRepository(Settings(Path('.'), {'DB_KIND':'demo'}))
        mapping = repository._columns(connection,'bi_reporting.b2b_project_segmented')
        self.assertEqual(mapping['seg_3'],'seg_3')
        self.assertIn('pg_catalog.pg_attribute', str(connection.execute.call_args.args[0]))
        connection.execute.return_value.fetchall.return_value = [(f,) for f in RAW_COLUMNS if f != 'series']
        with self.assertRaisesRegex(AppError,'series'): repository._columns(connection,'bi_reporting.b2b_project_segmented')
    def test_only_old_shipped_relation_is_migrated(self):
        raw = b'# preserved\r\nb2b_raw_table = "bi_reporting.b2b_project"\r\nSECRET=untouched'
        changed = migrate_segmented_source(raw)
        self.assertEqual(changed, raw.replace(b'bi_reporting.b2b_project',b'bi_reporting.b2b_project_segmented'))
        self.assertEqual(migrate_segmented_source(changed),changed)
        custom=b'B2B_RAW_TABLE=custom.view\n'
        self.assertEqual(migrate_segmented_source(custom),custom)
        bom = b'\xef\xbb\xbfB2B_RAW_TABLE=bi_reporting.b2b_project\r\n'
        self.assertEqual(migrate_segmented_source(bom),bom.replace(b'b2b_project',b'b2b_project_segmented'))
    def test_prompt_documents_user_vocabulary_without_claiming_live_inventory(self):
        prompt = PlannerClient(Settings(Path('.'), {'DB_KIND':'demo'})).system_prompt()
        for term in ('biz_group', 'seg_1', 'seg_2', 'seg_3', 'series', 'S(N-1)', 'not an exhaustive inventory', 'ask which level'):
            self.assertIn(term, prompt)
    def test_source_upgrade_is_backed_up_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); env = home/'.env'
            original = b'B2B_RAW_TABLE=bi_reporting.b2b_project\r\nB2B_ENABLE_ACCEPTANCE_UI=false\r\n'
            env.write_bytes(original)
            migrate(home, ROOT, 'f'*32)
            self.assertEqual(env.read_bytes(), original.replace(b'b2b_project', b'b2b_project_segmented'))
            restore(home, 'f'*32)
            self.assertEqual(env.read_bytes(), original)

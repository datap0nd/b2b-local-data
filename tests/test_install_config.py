"""Installer migrations use invented files and never touch the operator's config."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.install_config import enable_test_if_missing, known_shipped_rules, migrate, restore


class InstallConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'release'
        (self.release / 'config').mkdir(parents=True)
        (self.release / '.env.example').write_bytes(b'DB_KIND=demo\r\nB2B_ENABLE_ACCEPTANCE_UI=true\r\n')
        (self.release / 'config/business_rules.example.md').write_bytes(b'Corrected shipped rules\n')
        self.old_rules = b'Previous shipped rules\n'
        (self.release / 'config/shipped_business_rules.json').write_text(json.dumps({
            'versions': [{'source_commit': 'a' * 40, 'sha256': hashlib.sha256(self.old_rules).hexdigest()}]}))
        self.transaction = '1' * 32

    def test_append_preserves_every_original_byte_and_line_style(self):
        for raw, expected in (
            (b'', b'B2B_ENABLE_ACCEPTANCE_UI=true\r\n'),
            (b'\xef\xbb\xbf', b'\xef\xbb\xbfB2B_ENABLE_ACCEPTANCE_UI=true\r\n'),
            (b'# note\nDB_KIND=demo\n', b'# note\nDB_KIND=demo\nB2B_ENABLE_ACCEPTANCE_UI=true\n'),
            (b'# note\r\nDB_KIND=demo', b'# note\r\nDB_KIND=demo\r\nB2B_ENABLE_ACCEPTANCE_UI=true\r\n'),
            (b'LLM_API_KEY="secret#literal=$HOME"', b'LLM_API_KEY="secret#literal=$HOME"\r\nB2B_ENABLE_ACCEPTANCE_UI=true\r\n'),
            ('\ufeff# café\nDB_KIND=demo'.encode(), '\ufeff# café\nDB_KIND=demo\nB2B_ENABLE_ACCEPTANCE_UI=true\n'.encode()),
            (b'# B2B_ENABLE_ACCEPTANCE_UI=false\n', b'# B2B_ENABLE_ACCEPTANCE_UI=false\nB2B_ENABLE_ACCEPTANCE_UI=true\n'),
            (b'# mixed\r\nDB_KIND=demo\n', b'# mixed\r\nDB_KIND=demo\nB2B_ENABLE_ACCEPTANCE_UI=true\r\n'),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(enable_test_if_missing(raw), expected)
                self.assertEqual(enable_test_if_missing(expected), expected)

    def test_existing_assignment_is_never_overwritten_or_duplicated(self):
        for setting in (b'false', b'true', b'FALSE', b'"false"', b''):
            raw = b'\xef\xbb\xbf# note\r\n  b2B_enABLE_aCCEPTANCE_ui = ' + setting
            self.assertEqual(enable_test_if_missing(raw), raw)

    def test_invalid_env_is_rejected_before_any_files_are_written(self):
        raw = b'1INVALID=secret\n'
        (self.root / '.env').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'line 1'):
            migrate(self.root, self.release, self.transaction)
        self.assertEqual((self.root / '.env').read_bytes(), raw)
        self.assertFalse((self.root / 'business_rules.md').exists())
        self.assertFalse((self.root / '.config-backups').exists())

    def test_fresh_install_and_failed_configuration_rollback(self):
        self.assertEqual(migrate(self.root, self.release, self.transaction), ['.env', 'business_rules.md'])
        self.assertIn(b'B2B_ENABLE_ACCEPTANCE_UI=true', (self.root / '.env').read_bytes())
        restore(self.root, self.transaction)
        restore(self.root, self.transaction)
        self.assertFalse((self.root / '.env').exists())
        self.assertFalse((self.root / 'business_rules.md').exists())

    def test_known_rule_defaults_migrate_with_byte_exact_restoration(self):
        env = b'\xef\xbb\xbf# secret remains local\r\nDB_KIND=demo'
        rules = b'\xef\xbb\xbfPrevious shipped rules\r\n'
        (self.root / '.env').write_bytes(env)
        (self.root / 'business_rules.md').write_bytes(rules)
        self.assertTrue(known_shipped_rules(rules, self.release))
        migrate(self.root, self.release, self.transaction)
        self.assertEqual((self.root / 'business_rules.md').read_bytes(), b'Corrected shipped rules\n')
        self.assertEqual(migrate(self.root, self.release, '2' * 32), [])
        restore(self.root, self.transaction)
        self.assertEqual((self.root / '.env').read_bytes(), env)
        self.assertEqual((self.root / 'business_rules.md').read_bytes(), rules)

    def test_custom_rules_and_explicit_false_survive_unchanged(self):
        rules = self.old_rules + b'Local custom vocabulary\n'
        env = b'B2B_ENABLE_ACCEPTANCE_UI=false\n'
        (self.root / 'business_rules.md').write_bytes(rules)
        (self.root / '.env').write_bytes(env)
        self.assertFalse(known_shipped_rules(rules, self.release))
        self.assertEqual(migrate(self.root, self.release, self.transaction), [])
        self.assertEqual((self.root / 'business_rules.md').read_bytes(), rules)
        self.assertEqual((self.root / '.env').read_bytes(), env)

    def test_partial_write_failure_restores_original_files(self):
        from scripts import install_config
        original = install_config.atomic_write
        count = 0
        def fail_second_write(target, raw):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('simulated write failure')
            original(target, raw)
        env = b'DB_KIND=demo\n'
        (self.root / '.env').write_bytes(env)
        with patch.object(install_config, 'atomic_write', side_effect=fail_second_write):
            with self.assertRaisesRegex(OSError, 'simulated write failure'):
                migrate(self.root, self.release, self.transaction)
        self.assertEqual((self.root / '.env').read_bytes(), env)
        self.assertFalse((self.root / 'business_rules.md').exists())

    def test_restore_does_not_overwrite_new_operator_edits(self):
        migrate(self.root, self.release, self.transaction)
        current = (self.root / '.env').read_bytes() + b'# added after setup\n'
        (self.root / '.env').write_bytes(current)
        with self.assertRaisesRegex(ValueError, 'manual review'):
            restore(self.root, self.transaction)
        self.assertEqual((self.root / '.env').read_bytes(), current)
        self.assertTrue((self.root / 'business_rules.md').exists())

    def test_transaction_paths_and_backup_targets_are_bounded(self):
        for transaction in ('../outside', 'g' * 32, '1' * 40):
            with self.assertRaises(ValueError):
                migrate(self.root, self.release, transaction)
        migrate(self.root, self.release, self.transaction)
        manifest = self.root / '.config-backups' / self.transaction / 'manifest.json'
        manifest.write_text(json.dumps({'version': 1, 'files': [{'name': '../outside'}]}))
        with self.assertRaisesRegex(ValueError, 'target'):
            restore(self.root, self.transaction)

    def test_command_does_not_print_config_or_secret_values(self):
        (self.root / '.env').write_bytes(b'LLM_API_KEY=private-sentinel-123\n')
        helper = Path(__file__).resolve().parents[1] / 'scripts/install_config.py'
        command = subprocess.run([sys.executable, str(helper), '--home', str(self.root),
                                  '--release', str(self.release), '--transaction', self.transaction], capture_output=True, text=True)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertNotIn('private-sentinel-123', command.stdout + command.stderr)

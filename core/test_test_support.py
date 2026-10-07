"""The fixture override cannot silently redirect tests to C: or create at import."""
import importlib
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import test_support


class FixtureStorageTests(unittest.TestCase):
    def test_import_does_not_create_any_directory(self):
        with patch.object(Path, 'mkdir', side_effect=AssertionError('No import writes')):
            importlib.reload(test_support)

    def test_guarded_override_creates_missing_parent_lazily(self):
        with tempfile.TemporaryDirectory(dir=test_support.fixture_root()) as directory:
            root=Path(directory)/'not-created-yet'
            self.assertFalse(root.exists())
            with patch.dict(os.environ, {'NEXEN_TEST_ROOT':str(root)}):
                self.assertEqual(test_support.fixture_root(),root.resolve())
            self.assertTrue(root.is_dir())

    def test_disallowed_override_is_rejected_before_mkdir(self):
        with patch.dict(os.environ, {'NEXEN_TEST_ROOT':'C:/forbidden-fixture'}), \
             patch.object(Path,'mkdir',side_effect=AssertionError('No disallowed writes')):
            with self.assertRaises(ValueError):test_support.fixture_root()


class CoreDefinitionLoaderTests(unittest.TestCase):
    def test_load_definitions_without_startup_or_module_registration(self):
        canonical = Path(test_support.__file__).resolve().with_name('nexen.py')
        hub = ModuleType('nexen_hub')
        hub.register = Mock(side_effect=AssertionError('No hub registration'))
        missing = object()
        previous_nexen = sys.modules.get('nexen', missing)
        with patch.dict(sys.modules, {'nexen_hub': hub}), \
             patch.object(sqlite3, 'connect', side_effect=AssertionError('No database connection')) as connect, \
             patch('fastapi.FastAPI', side_effect=AssertionError('No application construction')) as application:
            core = test_support.load_core_definitions()
            connect.assert_not_called()
            application.assert_not_called()
            hub.register.assert_not_called()
            self.assertIs(sys.modules['nexen_hub'], hub)
            self.assertIs(sys.modules.get('nexen', missing), previous_nexen)
            self.assertFalse(any(value is core for value in sys.modules.values()))
        self.assertIsInstance(core, ModuleType)
        self.assertEqual(Path(core.__file__), canonical)
        self.assertEqual(core.BASE, canonical.parent)
        self.assertIn('CREATE TABLE IF NOT EXISTS jobs(', core.SCHEMA)
        self.assertIn('FACT', core.KINDS)
        for name in ('DB', 'Ingestor', 'ModelRouter', 'Analyzer', 'Supervisor', 'load_config'):
            self.assertTrue(callable(getattr(core, name)), name)
        for name in ('cfg', 'db', 'sup', 'app', 'register_hub'):
            self.assertNotIn(name, vars(core), name)

    def test_independent_loads_keep_function_globals_and_mutable_constants_isolated(self):
        first = test_support.load_core_definitions()
        original_base = first.BASE
        patched_base = original_base / 'fixture-only-base'
        first_config = {'paths': {'database': 'first.db', 'marvin_reports': 'reports', 'generated_workflows': 'workflows'}}
        with patch.object(first, 'BASE', patched_base), \
             patch.object(first, 'load_yaml', return_value=first_config) as first_yaml:
            first.KINDS.add('FIXTURE_ONLY_KIND')
            second = test_support.load_core_definitions()
            self.assertIsNot(first, second)
            self.assertIs(first.load_config.__globals__, vars(first))
            self.assertIs(second.load_config.__globals__, vars(second))
            self.assertIsNot(first.DB, second.DB)
            self.assertEqual(second.BASE, original_base)
            self.assertIsNot(second.load_yaml, first_yaml)
            self.assertNotIn('FIXTURE_ONLY_KIND', second.KINDS)
            self.assertEqual(first.load_config()['paths']['database'], str((patched_base / 'first.db').resolve()))
            first_yaml.assert_called_once_with(patched_base / 'config' / 'nexen.yaml')
            second_config = {'paths': {'database': 'second.db', 'marvin_reports': 'reports', 'generated_workflows': 'workflows'}}
            with patch.object(second, 'load_yaml', return_value=second_config) as second_yaml:
                self.assertEqual(second.load_config()['paths']['database'], str((original_base / 'second.db').resolve()))
                second_yaml.assert_called_once_with(original_base / 'config' / 'nexen.yaml')
            self.assertEqual(first_yaml.call_count, 1)

    def test_missing_or_renamed_startup_boundary_rejects_before_execution(self):
        for boundary in ('', 'config = load_config()', 'cfg = renamed_load_config()'):
            with self.subTest(boundary=boundary):
                source = "raise AssertionError('Unverified source must not execute')\n" + boundary + '\n'
                with patch.object(Path, 'read_text', return_value=source):
                    with self.assertRaises(RuntimeError):
                        test_support.load_core_definitions()


if __name__=='__main__':unittest.main()


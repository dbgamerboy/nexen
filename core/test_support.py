"""Isolated core definitions and lazy H/F test storage; no live app import."""
import ast
import os
from pathlib import Path
from types import ModuleType
from unittest import SkipTest

from storage_policy import require_output_path


def load_core_definitions():
    """Compile canonical core code without crossing its app-startup boundary.

    Each caller gets a fresh module namespace, so fixture patches cannot leak
    between test modules. Class bodies and their line numbers remain unchanged.
    Never register this namespace as the production ``nexen`` module.
    """
    source = Path(__file__).with_name('nexen.py')
    tree = ast.parse(source.read_text(encoding='utf-8-sig'), filename=str(source))
    boundary = next((index for index, node in enumerate(tree.body)
                     if isinstance(node, ast.Assign) and len(node.targets) == 1
                     and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'cfg'
                     and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Name) and node.value.func.id == 'load_config'
                     and not node.value.args and not node.value.keywords), None)
    if boundary is None:
        raise RuntimeError('The canonical core startup boundary was not found; no source was executed.')
    prefix = ast.Module(body=tree.body[:boundary], type_ignores=[])
    core = ModuleType('nexen_test_core')
    core.__file__ = str(source)
    exec(compile(prefix, str(source), 'exec'), core.__dict__)
    return core


def fixture_root():
    """Create a checked parent only when a test needs a temporary directory."""
    configured = os.environ.get('NEXEN_TEST_ROOT')
    if configured:
        root = require_output_path(configured)
    elif Path('H:/').is_dir():
        root = require_output_path('H:/NEXEN/temp/tests')
    elif Path('F:/').is_dir():
        root = require_output_path('F:/NEXEN_CACHE/test-fixtures')
    else:
        raise SkipTest('These Windows-local tests require H: or F: storage; no other drive is used.')
    root.mkdir(parents=True, exist_ok=True)
    return require_output_path(root)

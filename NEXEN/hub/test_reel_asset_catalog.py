"""Reel bundles appear in the existing shared workflow catalog."""
import json
from pathlib import Path
import tempfile
import unittest

from test_support import fixture_root
from workflow_workspace import WorkflowWorkspace


class ReelAssetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=fixture_root(), prefix='reel-catalog-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.ident = '57fe329c3a53dea074c6d7ed'
        bundle = self.assets / self.ident
        bundle.mkdir()
        (bundle / 'metadata.json').write_text(json.dumps({
            'asset_id': self.ident, 'source_id': 'fixture-source', 'lifecycle': 'captured'}), encoding='utf-8')
        (bundle / 'preview.json').write_text(json.dumps({
            'id': self.ident, 'skill_id': self.ident, 'workflow_id': self.ident,
            'title': 'Fixture reel method', 'one_line_purpose': 'Review a source-backed method.',
            'why': 'Retain the source context.', 'executable': False, 'source_url': 'https://example.test/source'}), encoding='utf-8')
        self.workspace = WorkflowWorkspace(db=None, root=self.root, app_root=self.root,
                                           reel_assets_root=self.assets)

    def test_shared_catalog_exposes_linked_skill_and_workflow_from_bundle(self):
        catalog = self.workspace.catalog(force=True)
        card = next(card for card in catalog['cards'] if card['id'] == self.ident)
        self.assertEqual(card['family'], 'reel')
        self.assertEqual(card['workflow_asset']['asset_id'], self.ident)
        self.assertEqual(card['workflow_asset']['skill_id'], self.ident)
        self.assertEqual(card['workflow_asset']['workflow_id'], self.ident)
        self.assertIn('reel_asset_bundle', [item['kind'] for item in card['provenance']])
        self.assertTrue(any('reference-only' in item.lower() for item in card['prerequisites']))

    def test_mismatched_bundle_identity_fails_closed_and_is_reported(self):
        preview = json.loads((self.assets / self.ident / 'preview.json').read_text(encoding='utf-8'))
        preview['workflow_id'] = '000000000000000000000000'
        (self.assets / self.ident / 'preview.json').write_text(json.dumps(preview), encoding='utf-8')
        catalog = self.workspace.catalog(force=True)
        self.assertNotIn(self.ident, [card['id'] for card in catalog['cards']])
        self.assertTrue(any(error['source'] == 'reel asset bundle' for error in catalog['coverage']['errors']))


if __name__ == '__main__':
    unittest.main()

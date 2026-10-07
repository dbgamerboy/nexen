from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_support import fixture_root
from youtube_memory import YouTubeMemory
from reel_assets import ReelAssetRegistry, asset_id_for, register


URL = 'https://www.youtube.com/watch?v=w0S-khYCaB4'


class DB:
    def __init__(self, path):
        self.path = path
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,path TEXT UNIQUE,size_bytes INTEGER,mtime REAL,sha256 TEXT,extension TEXT,indexed_at TEXT,extraction_status TEXT,text_chars INTEGER);
            CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,file_id INTEGER,chunk_index INTEGER,text TEXT,created_at TEXT,UNIQUE(file_id,chunk_index));
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text,content='chunks',content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text); END;''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=3)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def rows(self, sql, params=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params)]

    def scalar(self, sql, params=()):
        with self.connect() as c:
            return c.execute(sql, params).fetchone()[0]


# Explicitly-labeled fixture transcript: this is authored test text, not a captured reel.
FIXTURE_TRANSCRIPT = ('[00:03] Import the transcript into NEXEN memory.\n'
                       '[01:20] Compile a source-cited workflow draft.\n'
                       '[02:10] Build the paired reel asset bundle.')


def fixture_workflow_draft(prompt, model, profile=None, source_refs=None):
    return json.dumps({
        'title': 'Agentic OS reel workflow', 'summary': 'Turn the reel into a cited, reviewable pipeline.',
        'steps': [
            {'title': 'Import transcript', 'instruction': 'Import the transcript into NEXEN memory.', 'source_refs': ['s1']},
            {'title': 'Compile draft', 'instruction': 'Compile a source-cited workflow draft.', 'source_refs': ['s2']},
            {'title': 'Build asset', 'instruction': 'Build the paired reel asset bundle.', 'source_refs': ['s3']},
        ],
        'blockers': [],
    })


class ReelAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=fixture_root(), prefix='reel-assets-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = DB(self.root / 'test.sqlite3')
        self.youtube = YouTubeMemory(self.db, root=self.root / 'youtube', background=False, model_gate=lambda: None,
                                      generator=fixture_workflow_draft)
        self.registry = ReelAssetRegistry(self.db, self.youtube, root=self.root / 'reel-assets')

    def ready_source(self, text=FIXTURE_TRANSCRIPT, title='Fixture: reel-to-asset source'):
        item = self.youtube.create({'url': URL, 'title': title, 'transcript': text})
        return self.youtube.process(item['id'])

    def compile_workflow(self, source_id):
        self.youtube.compile(source_id, {'kind': 'workflow', 'model': 'fixture-model'})
        self.youtube.process_compile(source_id)
        return self.youtube.get(source_id, full=True)

    def test_canonical_id_is_deterministic_and_shared_across_skill_and_workflow(self):
        source = self.ready_source()
        expected = asset_id_for(source['id'])
        asset = self.registry.create({'source_id': source['id']})
        self.assertEqual(asset['id'], expected)
        self.assertEqual(asset['preview']['skill_id'], expected)
        self.assertEqual(asset['preview']['workflow_id'], expected)
        self.assertEqual(asset['metadata']['asset_id'], expected)
        again = self.registry.create({'source_id': source['id']})
        self.assertEqual(again['id'], expected)
        self.assertEqual(self.registry.listing()['count'], 1)

    def test_reference_only_bundle_when_no_compiled_draft(self):
        source = self.ready_source()
        asset = self.registry.create({'source_id': source['id']})
        self.assertFalse(asset['executable'])
        self.assertEqual(asset['lifecycle'], 'captured')
        self.assertEqual(asset['workflow']['status'], 'reference_only')
        self.assertFalse(asset['workflow']['executable'])
        self.assertTrue(asset['preview']['actions']['open_workflow'])
        self.assertFalse(asset['preview']['actions']['run_workflow'])
        self.assertIn('reviewed nodes', asset['workflow']['next_action'])
        bundle = Path(self.registry.root) / asset['id']
        for name in ('SKILL.md', 'workflow.json', 'diagram.mmd', 'metadata.json', 'preview.json'):
            self.assertTrue((bundle / name).is_file(), name)
        self.assertTrue((bundle / 'diagram.svg').is_file())
        self.assertIn('<svg', (bundle / 'diagram.svg').read_text(encoding='utf-8'))
        self.assertTrue((bundle / 'source' / 'README.md').is_file())
        self.assertTrue((bundle / 'source' / 'transcript.md').is_file())
        self.assertTrue((bundle / 'source' / 'verification.md').is_file())
        self.assertTrue((bundle / 'diagram.svg').is_file())
        self.assertIn('<svg', (bundle / 'diagram.svg').read_text(encoding='utf-8'))
        self.assertTrue((bundle / 'screenshots').is_dir())

    def test_converted_placeholder_stays_non_executable_until_adapter_review(self):
        source = self.ready_source()
        compiled = self.compile_workflow(source['id'])
        self.assertEqual(compiled['compile_status'], 'draft_ready')
        asset = self.registry.create({'source_id': source['id']})
        self.assertFalse(asset['executable'])
        self.assertEqual(asset['lifecycle'], 'converted')
        self.assertFalse(asset['workflow']['executable'])
        self.assertEqual(asset['workflow']['status'], 'reference_only')
        # Manual trigger + 3 cited steps, all documented as placeholders.
        self.assertEqual(len(asset['workflow']['nodes']), 4)
        self.assertEqual(asset['workflow']['meta']['nexen_asset_id'], asset['id'])
        self.assertEqual(asset['workflow']['asset_id'], asset['preview']['skill_id'])
        self.assertEqual(asset['workflow']['skill_id'], asset['preview']['skill_id'])
        self.assertEqual(asset['workflow']['workflow_id'], asset['preview']['workflow_id'])
        self.assertIn('Import transcript', asset['diagram_mermaid'])
        self.assertEqual(asset['preview']['actions']['open_workflow'], '/api/reel-assets/%s/workflow' % asset['id'])
        self.assertIsNone(asset['preview']['actions']['run_workflow'])
        self.assertIn('NoOp placeholders', asset['preview']['what_happens_if_run'])
        self.assertEqual(len(asset['preview']['when_to_use']), 3)
        self.assertTrue((Path(self.registry.root) / asset['id'] / 'source' / 'transcript.md').is_file())
        self.assertTrue(asset['metadata']['lifecycle_status']['converted'])
        self.assertFalse(asset['metadata']['lifecycle_status']['tested'])

    def test_rebuild_upgrades_lifecycle_in_place_without_new_row(self):
        source = self.ready_source()
        captured = self.registry.create({'source_id': source['id']})
        self.assertEqual(captured['lifecycle'], 'captured')
        compiled = self.compile_workflow(source['id'])
        self.assertEqual(compiled['compile_status'], 'draft_ready')
        converted = self.registry.create({'source_id': source['id']})
        self.assertEqual(converted['id'], captured['id'])
        self.assertEqual(converted['lifecycle'], 'converted')
        self.assertEqual(self.registry.listing()['count'], 1)

    def test_create_requires_ready_source(self):
        pending = self.youtube.create({'url': URL, 'title': 'Not ready yet'})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.registry.create({'source_id': pending['id']})

    def test_supplied_instagram_transcript_is_canonical_reference_asset(self):
        body = {'source_url': 'https://www.instagram.com/reel/fixture123/',
                'title': 'Captured Instagram example', 'transcript': '[00.20-02.00] Keep the original timestamp.\n'
                '[02.00-04.00] Do not invent missing creator metadata.'}
        asset = self.registry.create(body)
        self.assertEqual(asset['preview']['skill_id'], asset['preview']['workflow_id'])
        self.assertFalse(asset['executable'])
        self.assertEqual(asset['workflow']['status'], 'reference_only')
        self.assertIn('[0.20s]', asset['source_transcript'])
        self.assertIn('Creator: not recorded', asset['source_transcript'])
        self.assertEqual(asset['metadata']['creator'], None)

    def test_supplied_source_rejects_unsupported_urls_and_ambiguous_body(self):
        from pydantic import ValidationError
        from fastapi import HTTPException
        for url in ('http://evil.example/reel/x', 'https://www.instagram.com:invalid/reel/x'):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                self.registry.create({'source_url': url, 'transcript': 'source'})
        with self.assertRaises(ValidationError):
            self.registry.create({'source_url': 'https://instagram.com/reel/x', 'source_id': 'a' * 24,
                                  'transcript': 'source'})

    def test_listing_returns_preview_schema(self):
        source = self.ready_source()
        self.registry.create({'source_id': source['id']})
        listing = self.registry.listing()
        self.assertEqual(listing['count'], 1)
        preview = listing['assets'][0]
        for key in ('id', 'skill_id', 'workflow_id', 'title', 'one_line_purpose', 'why', 'when_to_use',
                    'diagram', 'screenshots', 'status', 'tags', 'executable', 'source_url', 'actions',
                    'what_happens_if_run', 'skill_id', 'workflow_id'):
            self.assertIn(key, preview)
        for key in ('open_skill', 'expand_preview', 'view_source'):
            self.assertIn(key, preview['actions'])
        self.assertEqual(preview['actions']['open_workflow'], '/api/reel-assets/%s/workflow' % preview['workflow_id'])

    def test_known_public_caption_provenance_does_not_get_labeled_user_supplied(self):
        from reel_assets import build_metadata
        source = self.ready_source()
        source['transcript_origin'] = 'youtube_caption_file'
        metadata = build_metadata(source, asset_id_for(source['id']), False)
        self.assertEqual(metadata['source_access'], 'public_youtube_caption')
        self.assertEqual(metadata['cost_type'], 'free_public_source')
        self.assertIsNone(metadata['creator'])
        self.assertIsNone(metadata['source_date'])

    def test_api_routes_round_trip(self):
        source = self.ready_source()
        compiled = self.compile_workflow(source['id'])
        self.assertEqual(compiled['compile_status'], 'draft_ready')
        app = FastAPI()
        with patch('pc_control.validate_request', lambda *a, **k: None):
            register(app, self.db, self.youtube, root=self.root / 'api-reel-assets')
            client = TestClient(app)
            created = client.post('/api/reel-assets', json={'source_id': source['id']})
            self.assertEqual(created.status_code, 200)
            asset_id = created.json()['id']
            listing = client.get('/api/reel-assets')
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()['count'], 1)
            detail = client.get('/api/reel-assets/' + asset_id)
            self.assertEqual(detail.status_code, 200)
            skill = client.get('/api/reel-assets/%s/skill' % asset_id)
            self.assertEqual(skill.status_code, 200)
            self.assertIn('Agentic OS reel workflow', skill.text)
            workflow = client.get('/api/reel-assets/%s/workflow' % asset_id)
            self.assertEqual(workflow.status_code, 200)
            self.assertFalse(workflow.json()['executable'])
            context = client.get('/api/reel-assets/%s/context' % asset_id)
            self.assertEqual(context.status_code, 200)
            self.assertEqual(context.json()['sequence'], ['skill', 'workflow'])
            self.assertEqual(context.json()['skill']['id'], context.json()['workflow']['id'])
            self.assertFalse(context.json()['workflow']['invocation_allowed'])
            diagram = client.get('/api/reel-assets/%s/diagram.svg' % asset_id)
            self.assertEqual(diagram.status_code, 200)
            self.assertTrue(diagram.headers['content-type'].startswith('image/svg+xml'))
            self.assertIn('<svg', diagram.text)
            page = client.get('/reel-assets')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Reel investment assets', page.text)


if __name__ == '__main__':
    unittest.main()

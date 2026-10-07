"""Isolated catalog/identity/action tests. No live n8n or external services."""
import asyncio
from contextlib import contextmanager, closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
import httpx

from task_tracking import Tracker, TaskCreate
from workflow_workspace import WorkflowWorkspace, graph_hash, register


class DB:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def rows(self, sql, params=()):
        with self.connect() as c:
            return [dict(x) for x in c.execute(sql, params)]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path('H:/NEXEN/enterprise/20260927/workflows/test-fixtures')
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        self.db = DB(self.root / 'tasks.sqlite3')
        Tracker(self.db)
        with self.db.connect() as c:
            c.execute('CREATE TABLE workflows(id INTEGER PRIMARY KEY,name,objective,executor,status,source_file_id)')
            c.executemany('INSERT INTO workflows VALUES(?,?,?,?,?,?)', [
                (1,'Research draft','Make a research draft','python','compiled',7),
                (2,'Research draft','Make a research draft','python','compiled',8),
                (3,'Research draft','Different result','python','candidate',9)])
        self.wf = dict(id='stable1',name='First method',nodes=[dict(id='node1',name='Manual',type='n8n-nodes-base.manualTrigger',parameters={})],connections={},settings={},active=False)
        folder = self.root / 'reels-finish/source-01-fixture'
        self.write(folder / 'workflow-video.json', self.wf)
        checkpoint = self.root / 'recovery/source-82-reconciliation-20260927/SOURCE-82-PROGRESS-CHECKPOINT-fixture.json'
        self.write(checkpoint, {'rows':[
            dict(source_id=1,method='A real source method',classification='actionable_method',h_source_folder=str(folder),next_action='Review input evidence.'),
            dict(source_id=2,method='Showcase only',classification='non_workflow',h_source_folder=str(folder.parent/'source-02-fixture'))]})
        backup = self.root/'backups/n8n-pre-f-repair-20260927/database.sqlite'
        backup.parent.mkdir(parents=True)
        with closing(sqlite3.connect(backup)) as c:
            c.execute('CREATE TABLE workflow_entity(id,name,nodes,connections,settings,active)')
            c.execute('INSERT INTO workflow_entity VALUES(?,?,?,?,?,?)',('stable1','First method',json.dumps(self.wf['nodes']),'{}','{}',1))
            c.execute('CREATE TABLE execution_entity(id,workflowId,status,startedAt,stoppedAt)')
            c.execute("INSERT INTO execution_entity VALUES(4,'stable1','success','2026-01-01','2026-01-02')")
            c.commit()
        self.write(backup.with_name('BACKUP-RECEIPT.json'), {'created_at_local':'2026-01-03'})
        self.write(self.root/'recovery/n8n-localhost-clean-20260926/NEXEN-LOCAL-IMPORT-20260927.json',[self.wf])
        self.write(self.root/'recovery/n8n-localhost-clean-20260926/NEXEN-ADDITIONS-ONLY-13-20260927.json',[])
        self.write(self.root/'recovery/exported-only-dry-import-20260927/EXPORTED-ONLY-SAFE-INACTIVE.json',[self.wf])
        self.write(self.root/'recovery/n8n-owner-preview-20260927/PROOF.json',dict(passed=True,graphs_match=True,checked_at_utc='2026-01-04'))
        self.write(self.app/'workflows/copy.json',self.wf)
        self.write(self.app/'data/generated_workflows/workflow_000001.json',dict(workflow_id=1,name='Research draft',objective='Make a research draft',executor='python'))
        (self.app/'workflows.html').write_text('<html>workflow test</html>')
        self.workspace = WorkflowWorkspace(self.db,self.root,self.app)

    def write(self,path,payload):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(payload),encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_package_asset_aliases_are_one_card(self):
        catalog=self.workspace.catalog()
        card=self.workspace.detail('source-01-video')
        self.assertEqual(len([c for c in catalog['cards'] if 'stable1' in c['n8n_ids']]),1)
        self.assertEqual(card['aliases'].count('n8n:stable1'),1)
        self.assertEqual(len(card['provenance']),6)
        self.assertEqual(card['status'],'recorded_active')
        self.assertEqual(card['last_execution']['status'],'success')
        self.assertIn('Historical',card['last_execution']['scope'])
        self.assertFalse(catalog['coverage']['live_n8n_queried'])
        self.assertIsNone(catalog['coverage']['cloud_workflow_total'])

    def test_every_proposal_id_and_evidence_only_source_is_represented(self):
        catalog=self.workspace.catalog()
        proposals=[c for c in catalog['cards'] if c['family']=='proposal']
        self.assertEqual(len(proposals),2)
        self.assertEqual({a for c in proposals for a in c['aliases']},{'nexen:1','nexen:2','nexen:3'})
        self.assertTrue(all(c['status']=='proposal' for c in proposals))
        self.assertEqual(catalog['coverage']['source_ids'],[1,2])
        self.assertEqual(self.workspace.detail('source-02-evidence')['status'],'evidence_only')
        self.assertEqual(catalog['summary']['nexen_proposal_rows'],3)

    def test_variant_conflict_is_preserved_without_duplicate_id(self):
        wf=dict(self.wf,settings={'executionTimeout':10})
        self.write(self.root/'recovery/n8n-localhost-clean-20260926/NEXEN-LOCAL-IMPORT-20260927.json',[wf])
        card=self.workspace.detail('source-01-video')
        self.assertTrue(card['variant_conflict'])
        self.assertEqual(len(card['graph_hashes']),2)
        self.assertIn('variants differ',card['prerequisites'][0])

    def test_hash_ignores_layout_but_not_executable_parameters(self):
        clone=json.loads(json.dumps(self.wf))
        clone['nodes'][0].update(id='other',position=[10,99])
        self.assertEqual(graph_hash(clone),graph_hash(self.wf))
        clone['nodes'][0]['parameters']={'operation':'different'}
        self.assertNotEqual(graph_hash(clone),graph_hash(self.wf))

    def test_no_read_side_effects_and_idempotent_user_draft(self):
        self.workspace.catalog()
        self.assertEqual(self.db.rows('SELECT * FROM hub_requests'),[])
        first=self.workspace.create_draft('source-01-video','Use owner input.')
        second=self.workspace.create_draft('source-01-video')
        self.assertEqual(first['task_id'],second['task_id'])
        self.assertFalse(first['executed'])
        self.assertEqual(len(self.db.rows('SELECT * FROM hub_requests')),1)
        self.assertIn('Use owner input.',first['task']['next_step'])
        card=self.workspace.detail('source-01-video')
        self.assertEqual(card['task_ids'],[first['task_id']])
        self.assertEqual(card['last_result']['kind'],'preparation_task')

    def test_unknown_and_unsupported_actions_fail_closed(self):
        for ident,action,expected in [('source-01-video','run',409),('source-01-video','stop',409),('missing','run',404),('source-01-video','shell',404)]:
            with self.assertRaises(HTTPException) as e:
                self.workspace.resolve_action(ident,action)
            self.assertEqual(e.exception.status_code,expected)
        self.assertEqual(self.workspace.resolve_action('workspace-money','workspace')['href'],'/money')

    def test_no_parameters_credentials_or_execution_payloads_are_returned(self):
        wf=json.loads(json.dumps(self.wf))
        wf['nodes'][0]['parameters']={'secret':'private-sentinel-XYZ','url':'https://service/?token=private-sentinel-XYZ'}
        wf['nodes'][0]['credentials']={'serviceApi':{'id':'private-credential-id','name':'private-credential-name'}}
        self.write(self.app/'workflows/private.json',dict(wf,id='other'))
        serialized=json.dumps(self.workspace.catalog())
        self.assertNotIn('private-sentinel-XYZ',serialized)
        self.assertNotIn('private-credential-id',serialized)
        self.assertNotIn('private-credential-name',serialized)
        self.assertIn('serviceApi',serialized)

    def test_paired_home_cards_keep_start_gated_and_expose_credential_blockers(self):
        root=self.app/'workflows/instagram-reconstruction'
        for variant,role in [('video','video'),('user_stack','userstack')]:
            wf=dict(self.wf,name='Sample paired method · '+variant,active=False,
                meta={'nexen':{'catalog_id':'instagram:source-01:'+variant,
                    'source_id':'source-01','source_shortcode':'CaseSensitive9Ab',
                    'source_numbers':[1],'method':'Sample paired method',
                    'role':role,'variant':variant.upper(),'category':'Video & clips',
                    'launch_ready':False,'launch_state':'blocked_setup',
                    'required_software':[{'name':'Render adapter','category':'Video & clips',
                        'state':'not_implemented','reason':'Adapter remains pending.'}],
                    'required_credentials':[{'type':'renderApi','name':'Render API',
                        'reason':'Bind this credential in n8n; secret values stay private.'}]}},
                nodes=[dict(self.wf['nodes'][0],credentials={'renderApi':{'id':'secret-id','name':'secret-label'}})])
            self.write(root/(variant+'/sample.json'),wf)
        catalog=self.workspace.catalog(force=True,compact=True)
        paired=[c for c in catalog['cards'] if (c.get('workflow_asset_path') or '').replace('\\','/').startswith(str((self.app/'workflows/instagram-reconstruction').as_posix()))]
        self.assertEqual(len(paired),2)
        self.assertEqual({c['variant'] for c in paired},{'VIDEO','USER_STACK'})
        for card in paired:
            self.assertFalse(card['launch_ready'])
            self.assertFalse(next(a for a in card['actions'] if a['id']=='run')['enabled'])
            self.assertEqual(card['required_credentials'][0]['type'],'renderApi')
            self.assertEqual(card['source_shortcode'],'CaseSensitive9Ab')
        serialized=json.dumps(catalog)
        self.assertNotIn('secret-id',serialized)
        self.assertNotIn('secret-label',serialized)

    def test_corrupt_source_is_visible_in_coverage_and_does_not_claim_complete(self):
        (self.app/'workflows/broken.json').write_text('{bad')
        catalog=self.workspace.catalog()
        self.assertTrue(catalog['coverage']['errors'])
        self.assertEqual(catalog['coverage']['expected_source_rows'],82)
        self.assertEqual(len(catalog['coverage']['source_ids']),2)
        with self.assertRaises(ValueError):
            self.workspace.owned('F:/outside/workflow.json')

    def test_registered_mutation_rejects_cross_origin_and_unknown_card(self):
        app=FastAPI()
        register(app,self.db,self.workspace)
        async def check():
            transport=httpx.ASGITransport(app=app,client=('127.0.0.1',12345))
            async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1:8788') as client:
                response=await client.get('/api/workflows/catalog')
                self.assertEqual(response.status_code,200)
                self.assertNotIn('provenance',response.json()['cards'][0])
                response=await client.post('/api/workflows/source-01-video/draft',json={},headers={'Origin':'http://evil.invalid','X-Nexen-Action':'launch'})
                self.assertEqual(response.status_code,403)
                response=await client.post('/api/workflows/source-01-video/draft',json={},headers={'Origin':'http://127.0.0.1:8788','X-Nexen-Action':'launch'})
                self.assertEqual(response.status_code,200)
                self.assertFalse(response.json()['executed'])
                response=await client.post('/api/workflows/missing/draft',json={},headers={'Origin':'http://127.0.0.1:8788','X-Nexen-Action':'launch'})
                self.assertEqual(response.status_code,404)
        asyncio.run(check())

    def test_intake_candidates_preserve_existing_private_filter(self):
        root=self.root/'intake/phone-20260913'
        self.write(root/'manifest.json',dict(sources=[
            dict(source_id='phone-aaaaaaaaaaaa',source_name='Visible workflow'),
            dict(source_id='phone-bbbbbbbbbbbb',source_name='Private sentinel',private_source=True)]))
        self.write(root/'cards.json',[
            dict(id='visible',source_id='phone-aaaaaaaaaaaa',title='Visible workflow',workflow_quotes=['Prepare a draft.']),
            dict(id='private',source_id='phone-bbbbbbbbbbbb',title='Private sentinel',workflow_quotes=['Private content.'])])
        catalog=self.workspace.catalog()
        self.assertEqual(catalog['summary']['intake_candidate_rows'],1)
        self.assertEqual(catalog['summary']['private_intake_sources_hidden'],1)
        self.assertNotIn('Private sentinel',json.dumps(catalog))


if __name__=='__main__':
    unittest.main()

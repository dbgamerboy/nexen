"""Regression checks for persistent source intake without accidental execution."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,'H:/NEXEN/v1/app')
from task_tracking import Tracker, TaskCreate
import ticket_reconciliation as r


class ReconciliationTest(unittest.TestCase):
    def setUp(self):
        root=Path('H:/NEXEN/handoffs/ticket-reconciliation-20261003/work');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.path=Path(self.temp.name)/'fixture.db'
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('CREATE TABLE hub_requests(id INTEGER PRIMARY KEY,text TEXT,status TEXT,created_at TEXT)')
            c.commit()
        self.db=r.ExistingDB(self.path);self.tracker=Tracker(self.db)
        self.old=self.tracker.create(TaskCreate(text='Existing completed work'),seed_key='existing',initial_status='done')
        self.row={'id':'TEST-1','title':'Reconcile ticket sources','lane':'A','category':'tasks',
                  'priority':'high','status':'planned','source_refs':[{'path':'H:/source.txt','locator':'line 12'}],
                  'acceptance_checks':['Preserve original IDs and resolve duplicates without changing completed tasks.'],
                  'existing_task_ids':[]}
    def tearDown(self):
        self.temp.cleanup()
    def factory(self):
        return self.tracker,TaskCreate
    def test_repeat_apply_reuses_same_canonical_task(self):
        first=r.apply_plan([self.row],self.path,self.factory)
        second=r.apply_plan([self.row],self.path,self.factory)
        self.assertEqual(first[0]['canonical_task_ids'],second[0]['canonical_task_ids'])
        self.assertEqual(len(r.canonical_snapshot(self.path)),2)
        self.assertEqual(r.canonical_snapshot(self.path)[0]['status'],'done')
    def test_interrupted_partial_apply_resumes_without_duplication(self):
        rows=[self.row,{**self.row,'id':'TEST-2','title':'Second ticket'}]
        original=self.tracker.create
        def interrupted(body,**kw):
            if kw['seed_key'].endswith('TEST-2'):raise RuntimeError('simulated crash')
            return original(body,**kw)
        self.tracker.create=interrupted
        with self.assertRaises(RuntimeError):r.apply_plan(rows,self.path,self.factory)
        self.tracker.create=original
        r.apply_plan(rows,self.path,self.factory)
        self.assertEqual(len(r.canonical_snapshot(self.path)),3)
    def test_invalid_last_item_causes_zero_task_mutations(self):
        bad={**self.row,'id':'TEST-2','existing_task_ids':[999]}
        with self.assertRaises(ValueError):r.apply_plan([self.row,bad],self.path,self.factory)
        self.assertEqual(len(r.canonical_snapshot(self.path)),1)
    def test_no_transport_done_import(self):
        with self.assertRaises(ValueError):r.validate_requirements([{**self.row,'status':'done'}])
    def test_archived_deferred_proposal_never_becomes_canonical_task(self):
        result=r.apply_plan([{**self.row,'status':'blocked','import_action':'do_not_import'}],self.path,self.factory)
        self.assertEqual(result[0]['action'],'hold-source-only')
        self.assertEqual(len(r.canonical_snapshot(self.path)),1)
    def test_duplicate_source_identifier_rejected(self):
        source={'intake_id':'MASS-0001','title':'Source','src_path':'H:/x','src_locator':'1'}
        with self.assertRaises(ValueError):r.catalogue([source,source],[],[])
    def test_original_ids_and_private_boundary(self):
        source={'intake_id':'MASS-0001','private':True,'title':'private sample','source_variant_conflict':True}
        rows=r.catalogue([source],[],[])
        self.assertEqual(rows[0]['id'],'MASS-0001');self.assertEqual(rows[0]['status'],'hold-variant')
        self.assertNotIn('private sample',json.dumps(rows))
    def test_explicit_existing_task_preserves_done_status(self):
        row={**self.row,'existing_task_ids':[self.old]}
        result=r.apply_plan([row],self.path,self.factory)
        self.assertEqual(result[0]['action'],'reuse')
        self.assertEqual(r.canonical_snapshot(self.path)[0]['status'],'done')
    def test_ambiguous_exact_titles_do_not_guess_alias(self):
        canonical=[{'id':1,'text':self.row['title'],'seed_key':None},{'id':2,'text':self.row['title'],'seed_key':None}]
        with self.assertRaises(ValueError):r.plan([self.row],canonical)
    def test_changed_seed_replay_rejected(self):
        r.apply_plan([self.row],self.path,self.factory)
        with self.assertRaises(ValueError):r.apply_plan([{**self.row,'title':'Unrelated changed objective'}],self.path,self.factory)
    def test_duplicate_incoming_titles_require_review(self):
        with self.assertRaises(ValueError):r.plan([self.row,{**self.row,'id':'TEST-2'}],[])
    def test_crosswalk_detects_missing_and_wrong_member_targets(self):
        groups=[{'intake_id':'MASS-0001','member_intake_ids':['MASS-0001','S01-1']},{'intake_id':'AG-1'}]
        valid=[{'intake_id':'MASS-0001','ticket_id':'MASS-0001'},{'intake_id':'S01-1','ticket_id':'MASS-0001'},{'intake_id':'AG-1','ticket_id':'AG-1'}]
        self.assertEqual(r.validate_crosswalk(groups,valid),3)
        with self.assertRaises(ValueError):r.validate_crosswalk(groups,valid[:-1])
        with self.assertRaises(ValueError):r.validate_crosswalk(groups,[*valid[:-1],{'intake_id':'AG-1','ticket_id':'MASS-0001'}])
    def test_missing_acceptance_or_source_ref_rejected(self):
        for field in ['acceptance_checks','source_refs']:
            with self.assertRaises(ValueError):r.validate_requirements([{**self.row,field:[]}])
    def test_two_concurrent_creates_share_existing_tracker_seed(self):
        def seed(_):return Tracker(r.ExistingDB(self.path)).create(TaskCreate(text='Concurrent'),seed_key='parallel')
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(seed,range(2)))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(len(r.canonical_snapshot(self.path)),2)
    def test_browser_text_is_escaped_and_reuses_existing_sanitizer(self):
        out=Path(self.temp.name)/'out'
        source=[{'intake_id':'MASS-0001','title':'</script><script>alert(1)</script>','src_path':'H:/x','src_locator':'1'}]
        r.write_report(out,source,[],[],r.load_sanitizer())
        html=(out/'NEXEN-V3-TICKETS.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><script>alert(1)',html)
        self.assertIn('td.textContent=v',html)
        self.assertEqual(r.load_sanitizer()({'password':'fixture-private'}),{'password':'[CREDENTIAL REDACTED]'})
    def test_snapshot_closes_connection_for_windows_rename(self):
        r.canonical_snapshot(self.path)
        renamed=self.path.with_name('moved.db')
        self.path.rename(renamed);renamed.rename(self.path)
    def test_secondary_ids_and_stale_running_preserved_honestly(self):
        out=Path(self.temp.name)/'out'
        inventory={'secondary_tracker':{'database':'H:/secondary.db','tickets':[{'id':'NX-001','title':'Worker','status':'running','lease_active':False,'lane':'D'}]},
                   'canonical':{'tasks':[{'id':self.old,'private':True}]}}
        counts=r.write_report(out,[],r.canonical_snapshot(self.path),[],lambda x:x,inventory)
        rows=r.read_json(out/'TICKET-CATALOG.json')['rows']
        self.assertEqual(counts['secondary_worker_tickets'],1)
        self.assertIn('PRIVATE',rows[0]['title']);self.assertEqual(rows[1]['status'],'running')
        self.assertIn('inactive',rows[1]['evidence_status'])


if __name__=='__main__':unittest.main()

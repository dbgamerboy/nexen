"""Real pinned contract tests in H: fixtures; no native n8n, model, or account calls."""
from contextlib import contextmanager
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from fastapi import FastAPI, HTTPException
import httpx

from task_tracking import Tracker, TaskCreate
from workflow_execution import (WorkflowExecution, RunRequest, SOURCE, SOURCE_SHA256,
    NODE_INVENTORY, CARD_ID, sha, encoded, validate_packet)


class DB:
    def __init__(self, path): self.path = path
    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def rows(self, sql, params=()):
        with self.connect() as c: return [dict(x) for x in c.execute(sql, params)]


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes = SOURCE.read_bytes()
        if sha(cls.source_bytes) != SOURCE_SHA256:
            raise AssertionError('Source changed; source review must precede tests.')
        cls.native_prior = json.loads(Path('H:/NEXEN/validation/service-offer-native-20260927/SERVICE-OFFER-REVIEW-DRAFT.json').read_text(encoding='utf-8-sig'))

    def setUp(self):
        base = Path('H:/NEXEN/enterprise/20260927/workflow-execution/test-fixtures')
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.json'
        self.source.write_bytes(self.source_bytes)
        self.db = DB(self.root / 'tasks.sqlite3')
        self.tracker = Tracker(self.db)
        self.task = self.tracker.create(TaskCreate(text='Source 78 fixture preparation'), seed_key='workflow-card:' + CARD_ID)
        self.service = WorkflowExecution(self.db, root=self.root / 'service', source=self.source)
        self.packet = dict(native_input={k:self.native_prior[k] for k in ('profile','responses','selected_service_id')},
            input_basis=dict(kind='fixture', owner_confirmed=False, skills_basis='Historical synthetic test inputs, not owner ability.',
                hours_basis='Historical planning fixture, not actual availability.', evidence_refs=['Prior disposable native execution proof'],
                unknowns=['Owner skills and available time are unconfirmed.']))
        (self.service.root / 'CURRENT-DRAFT-INPUT.json').write_text(encoded(self.packet), encoding='utf-8')

    def tearDown(self):
        if self.service._thread: self.service._thread.join(20)
        self.temp.cleanup()

    def request(self, key='a'*32, packet=None):
        packet = packet or self.packet
        return RunRequest(request_key=key, source_sha256=SOURCE_SHA256, input_sha256=sha(encoded(packet)), packet=packet)

    def wait(self, ident):
        if self.service._thread: self.service._thread.join(20)
        self.assertFalse(self.service._thread and self.service._thread.is_alive())
        return self.service.get(ident)

    def run_packet(self, packet=None, key='a'*32):
        prepared=self.service.prepare(self.request(key, packet))
        self.service.start(prepared['id'])
        return self.wait(prepared['id'])

    def test_exact_native_fixture_parity_and_owner_gate(self):
        receipt=self.run_packet()
        self.assertEqual(receipt['status'],'needs_owner_profile_confirmation',receipt.get('error'))
        self.assertTrue(receipt['executed'])
        self.assertFalse(receipt['native_n8n_execution'])
        self.assertEqual(receipt['model_calls'],0)
        self.assertEqual(receipt['accepted_stages'],[1,2,3,4,5])
        self.assertEqual([x['node'] for x in receipt['contract_trace']],[x[0] for x in NODE_INVENTORY])
        result=self.service.result(receipt['id'])
        # Whole parsed native result equality, including outputs and stable job key.
        self.assertEqual(result['source_result'],self.native_prior)
        self.assertEqual(result['operational_state'],'needs_owner_profile_confirmation')
        self.assertEqual(self.tracker.get(self.task)['status'],'planned')
        self.assertEqual(len(self.tracker.get(self.task)['history']),1)

    def test_empty_responses_produce_real_next_stage_handoff(self):
        packet=json.loads(encoded(self.packet));packet['native_input']['responses']={};packet['native_input']['selected_service_id']=''
        receipt=self.run_packet(packet)
        self.assertEqual(receipt['status'],'needs_manual_response',receipt.get('error'))
        result=self.service.result(receipt['id'])
        self.assertEqual(result['source_result']['next_stage'],1)
        self.assertEqual(result['source_result']['accepted_stages'],[])
        self.assertIn('Existing ChatGPT account',result['source_result']['handoff']['provider'])
        self.assertEqual(result['operational_state'],'needs_owner_profile_confirmation')

    def test_native_schema_rejection_is_failed_not_success(self):
        packet=json.loads(encoded(self.packet));packet['native_input']['responses']['3']['send_automatically']=True
        receipt=self.run_packet(packet)
        self.assertEqual(receipt['status'],'failed')
        self.assertIn('Sending is not authorized',receipt['error'])
        self.assertFalse(receipt['executed'])
        self.assertIsNone(receipt['result_sha256'])

    def test_skills_stage_order_and_capacity_are_not_weakened(self):
        for index,change in enumerate(('skill','order','capacity')):
            packet=json.loads(encoded(self.packet))
            if change=='skill':packet['native_input']['responses']['1']['services'][0]['skill_used']='Unknown skill'
            if change=='order':del packet['native_input']['responses']['1']
            if change=='capacity':packet['native_input']['profile']['hours_available']=.1
            receipt=self.run_packet(packet,key=('%032x'%index))
            self.assertEqual(receipt['status'],'failed',change)

    def test_stricter_adaptation_limit_and_secret_rejection(self):
        packet=json.loads(encoded(self.packet));packet['native_input']['responses']['5']['outreach_count']=6
        with self.assertRaises(ValueError):validate_packet(packet)
        packet=json.loads(encoded(self.packet));packet['input_basis']['skills_basis']='api_key=private-sentinel-value'
        with self.assertRaises(ValueError):validate_packet(packet)

    def test_idempotency_no_duplicate_run_and_request_collision(self):
        first=self.service.prepare(self.request());second=self.service.prepare(self.request())
        self.assertEqual(first['id'],second['id'])
        self.service.start(first['id']);receipt=self.wait(first['id'])
        again=self.service.start(first['id']);self.assertEqual(again['result_sha256'],receipt['result_sha256'])
        self.assertEqual(len(self.db.rows('SELECT * FROM workflow_local_runs')),1)
        self.assertEqual(len(self.tracker.get(self.task)['history']),1)
        packet=json.loads(encoded(self.packet));packet['input_basis']['hours_basis']='Different planning basis'
        with self.assertRaises(HTTPException) as error:self.service.prepare(self.request(packet=packet))
        self.assertEqual(error.exception.status_code,409)

    def test_source_input_and_runner_hash_guards(self):
        with self.assertRaises(HTTPException):self.service.prepare(self.request().model_copy(update={'source_sha256':'0'*64}))
        with self.assertRaises(HTTPException):self.service.prepare(self.request().model_copy(update={'input_sha256':'0'*64}))
        prepared=self.service.prepare(self.request())
        self.service.path(prepared['id'],'runner.cjs').write_text('throw Error("changed")',encoding='utf-8')
        self.service.start(prepared['id']);receipt=self.wait(prepared['id'])
        self.assertEqual(receipt['status'],'failed');self.assertIn('modified',receipt['error'])
        self.source.write_bytes(self.source_bytes+b' ')
        self.assertFalse(self.service.review()['enabled'])
        with self.assertRaises(HTTPException):self.service.prepare(self.request(key='b'*32))

    def test_saved_input_tamper_does_not_execute(self):
        prepared=self.service.prepare(self.request());path=self.service.path(prepared['id'],'input.json')
        packet=json.loads(path.read_text(encoding='utf-8'));packet['input_basis']['hours_basis']='Changed after prepare';path.write_text(encoded(packet),encoding='utf-8')
        self.service.start(prepared['id']);receipt=self.wait(prepared['id'])
        self.assertEqual(receipt['status'],'failed');self.assertIn('input packet was modified',receipt['error'])

    def test_cancel_before_and_during_run(self):
        prepared=self.service.prepare(self.request());receipt=self.service.cancel(prepared['id'])
        self.assertEqual(receipt['status'],'cancelled');self.assertFalse(receipt['executed'])
        self.assertEqual(self.service.start(prepared['id'])['status'],'cancelled')
        started,release=threading.Event(),threading.Event();original=self.service._checkpoint
        def checkpoint(folder,when):
            started.set();release.wait(3);original(folder,when)
        self.service._checkpoint=checkpoint
        prepared=self.service.prepare(self.request(key='b'*32));self.service.start(prepared['id']);self.assertTrue(started.wait(3))
        self.service.cancel(prepared['id']);release.set();receipt=self.wait(prepared['id'])
        self.assertEqual(receipt['status'],'cancelled');self.assertFalse(receipt['executed'])

    def test_maximum_runtime_and_result_integrity(self):
        self.service.max_seconds=.000001
        receipt=self.run_packet();self.assertEqual(receipt['status'],'failed');self.assertIn('maximum runtime',receipt['error'])
        self.service.max_seconds=15
        receipt=self.run_packet(key='b'*32);self.assertTrue(receipt['result_sha256'])
        self.service.path(receipt['id'],'result.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(HTTPException) as error:self.service.result(receipt['id'])
        self.assertEqual(error.exception.status_code,409)

    def test_recovery_preserves_draft_and_never_retries(self):
        receipt=self.service.prepare(self.request());receipt['status']='running';self.service.record(receipt)
        self.service.recover();recovered=self.service.get(receipt['id'])
        self.assertEqual(recovered['status'],'interrupted');self.assertFalse(recovered['executed'])
        self.assertEqual(self.service.start(receipt['id'])['status'],'interrupted')
        with self.assertRaises(HTTPException):self.service.get('../../elsewhere')

    def test_private_routes_only_run_supported_card_and_return_durable_result(self):
        from workflow_workspace import WorkflowWorkspace, register
        desk=WorkflowWorkspace(self.db,root=self.root,app_root=self.root)
        desk.execution=self.service
        app=FastAPI();register(app,self.db,desk)
        async def check():
            transport=httpx.ASGITransport(app=app,client=('127.0.0.1',12345))
            async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1:8788') as client:
                review=await client.get('/api/workflows/source-78-userstack/execution')
                self.assertTrue(review.json()['enabled'])
                headers={'Origin':'http://127.0.0.1:8788','X-Nexen-Action':'launch'}
                body=self.request().model_dump()
                bad=await client.post('/api/workflows/source-78-userstack/run',json=body,headers=dict(headers,Origin='http://other.invalid'))
                self.assertEqual(bad.status_code,403)
                bad=await client.post('/api/workflows/source-01-video/run',json=body,headers=headers)
                self.assertEqual(bad.status_code,409)
                self.assertEqual(len(self.db.rows('SELECT * FROM workflow_local_runs')),0)
                started=await client.post('/api/workflows/source-78-userstack/run',json=body,headers=headers)
                self.assertEqual(started.status_code,200)
                ident=started.json()['id'];await asyncio.to_thread(self.service._thread.join,20)
                receipt=await client.get('/api/workflows/executions/'+ident)
                self.assertEqual(receipt.json()['status'],'needs_owner_profile_confirmation')
                result=await client.get('/api/workflows/executions/'+ident+'/result')
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()['task_id'],self.task)
                again=await client.post('/api/workflows/source-78-userstack/run',json=body,headers=headers)
                self.assertEqual(again.json()['id'],ident)
                self.assertEqual(len(self.db.rows('SELECT * FROM workflow_local_runs')),1)
        asyncio.run(check())


if __name__=='__main__': unittest.main()

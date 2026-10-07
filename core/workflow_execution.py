"""One pinned Source 78 Code-node contract runner; no general workflow executor.

Trust comes from exact source review + the hardcoded whole-file hash. Node vm is
an execution context, NOT a security sandbox for arbitrary imported programs.
This executes existing validation/packaging code, never the native n8n scheduler
and never an LLM, outreach, account, payment, publishing, or activation adapter.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import threading
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from file_census import SingleWriter

ROOT = Path('H:/NEXEN/enterprise/20260927/workflow-execution')
SOURCE = Path('H:/NEXEN/reels-finish/source-78-service-sales-20260927/workflow-userstack.json')
SOURCE_SHA256 = 'd6636084e9f23a35a0fa4379b06f87ee791808ea67660921b301c3a7d5bd8d45'
NODE = Path('%USERPROFILE%/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
CARD_ID = 'source-78-userstack'
ADAPTER = 'source78-userstack-code-contract-v1'
MAX_SECONDS = 15
MAX_INPUT = 160000
MAX_RESULT = 1500000
TERMINAL = {'draft_ready', 'needs_owner_profile_confirmation', 'needs_manual_response', 'failed', 'cancelled', 'interrupted'}
NODE_INVENTORY = (
    ('Start service offer session', 'n8n-nodes-base.manualTrigger'),
    ('Edit service inputs', 'n8n-nodes-base.code'),
    ('1. Discover five services', 'n8n-nodes-base.code'),
    ('2. Build chosen offer', 'n8n-nodes-base.code'),
    ('3. Draft outreach', 'n8n-nodes-base.code'),
    ('4. Create free asset offer', 'n8n-nodes-base.code'),
    ('5. Plan first client day', 'n8n-nodes-base.code'),
    ('Prepare review download', 'n8n-nodes-base.code'),
    ('Download service package', 'n8n-nodes-base.convertToFile'),
)
ENGINE_SCOPE = ('Pinned n8n Code-node contract runner: supplied JSON is validated and packaged locally. '
                'This is not native n8n scheduler execution or model generation.')
PERMISSIONS = dict(external_spend=0, send_messages=False, publish=False, charge_customers=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def confined(root, candidate):
    """Reject linked components before resolving so no F: link is followed."""
    root, candidate = Path(root).absolute(), Path(candidate).absolute()
    if not candidate.is_relative_to(root):
        raise ValueError('Artifact is outside its owned folder.')
    for part in (candidate, *candidate.parents):
        if part.exists():
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Linked workflow paths are not permitted.')
    return candidate


def save_json(path, value):
    raw = encoded(value)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(raw, encoding='utf-8')
    os.replace(temp, path)


def validate_packet(packet):
    """Bound data and provenance; exact native field/stage validation stays in source code."""
    if not isinstance(packet, dict) or set(packet) != {'native_input', 'input_basis'}:
        raise ValueError('Use native_input and input_basis only.')
    native, basis = packet['native_input'], packet['input_basis']
    if not isinstance(native, dict) or set(native) != {'profile', 'responses', 'selected_service_id'}:
        raise ValueError('Source 78 requires profile, responses, and selected_service_id.')
    required_basis = {'kind', 'owner_confirmed', 'skills_basis', 'hours_basis', 'evidence_refs', 'unknowns'}
    optional_basis = {'operational_readiness', 'source_condition_note'}
    if not isinstance(basis, dict) or not required_basis <= set(basis) or set(basis) - required_basis - optional_basis:
        raise ValueError('Input basis must identify kind, owner confirmation, skill/time basis, evidence references, and unknowns.')
    if basis['kind'] not in ('current_assistant_draft', 'owner_entered', 'fixture') or type(basis['owner_confirmed']) is not bool:
        raise ValueError('Invalid input provenance or owner-confirmation field.')
    for field in ('skills_basis', 'hours_basis'):
        if not isinstance(basis[field], str) or not basis[field].strip() or len(basis[field]) > 2000:
            raise ValueError('Describe the ' + field + ' without guessing owner capability.')
    for field in ('evidence_refs', 'unknowns'):
        if not isinstance(basis[field], list) or len(basis[field]) > 30 or any(not isinstance(x, str) or len(x) > 2000 for x in basis[field]):
            raise ValueError('Invalid ' + field + ' list.')
    if not basis['owner_confirmed'] and not basis['unknowns']:
        raise ValueError('Unconfirmed inputs must identify what is unknown.')
    for field in optional_basis & set(basis):
        if not isinstance(basis[field], str) or len(basis[field]) > 2000:
            raise ValueError('Invalid source-condition metadata.')
    raw = encoded(packet)
    if len(raw.encode()) > MAX_INPUT:
        raise ValueError('Input exceeds the bounded draft size.')
    if re.search(r'(?i)(?:api[_ -]?key|access[_ -]?token|password|authorization)\s*[:=]\s*["\']?[^\s"\',;]{8,}|\bsk-[A-Za-z0-9_-]{20,}', raw):
        raise ValueError('Remove credential values from the draft input.')
    responses = native.get('responses')
    if isinstance(responses, dict) and isinstance(responses.get('5'), dict):
        count = responses['5'].get('outreach_count')
        if type(count) is not int or not 0 <= count <= 5:
            raise ValueError('The reviewed $0 adaptation permits zero through five unsent draft contacts only.')
    return packet


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(pattern=r'^[a-f0-9]{32}$')
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    input_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    packet: dict | None = None


# The node sequence and input-boundary substitution are explicit. Exact reviewed
# stage and packaging bodies come only from the hash-pinned source snapshot.
RUNNER = r'''"use strict";
const fs=require('node:fs'),crypto=require('node:crypto'),vm=require('node:vm');
const sourceBytes=fs.readFileSync('source.json');
if(crypto.createHash('sha256').update(sourceBytes).digest('hex')!=="SOURCE_HASH")throw Error('Reviewed source hash changed.');
const workflow=JSON.parse(sourceBytes.toString('utf8').replace(/^\uFEFF/,''));
const packet=JSON.parse(fs.readFileSync('input.json','utf8'));
let state=packet.native_input;
const trace=[{node:workflow.nodes[0].name,operation:'Explicit local request; native trigger not dispatched'},
 {node:workflow.nodes[1].name,operation:'Supplied saved JSON replaces historical Edit service inputs defaults'}];
try{
 for(const node of workflow.nodes.slice(2,8)){
  const context=vm.createContext({inputJson:JSON.stringify(state)},{codeGeneration:{strings:false,wasm:false}});
  const output=vm.runInContext('const $input={first:()=>({json:JSON.parse(inputJson)})};(()=>{'+node.parameters.jsCode+'\n})()',context,{timeout:1000});
  if(!Array.isArray(output)||output.length!==1||!output[0]||typeof output[0].json!=='object')throw Error('Invalid Code-node output contract.');
  state=JSON.parse(JSON.stringify(output[0].json));
  trace.push({node:node.name,operation:'Exact pinned Code body',status:'completed'});
 }
 const convert=workflow.nodes[8].parameters;
 if(convert.operation!=='toText'||convert.sourceProperty!=='bundleJson'||typeof state.bundleJson!=='string')throw Error('Unexpected Convert to File contract.');
 if(state.bundleName!==`service-offer-user-stack-${state.status}.json`)throw Error('Unexpected bundle name.');
 const result=JSON.parse(state.bundleJson);
 trace.push({node:workflow.nodes[8].name,operation:'Exact toText bundleJson serialization; saved local artifact, no native n8n binary item'});
 fs.writeFileSync('runner-result.json',JSON.stringify({result,trace,bundle_name:state.bundleName,runtime:process.version}));
}catch(error){process.stderr.write(String(error.message).slice(0,1000));process.exitCode=1}
'''.replace('SOURCE_HASH', SOURCE_SHA256)


class WorkflowExecution:
    def __init__(self, db, root=ROOT, source=SOURCE, node=NODE, max_seconds=MAX_SECONDS):
        self.db, self.root, self.source, self.node = db, Path(root).absolute(), Path(source).absolute(), Path(node).absolute()
        self.max_seconds = min(MAX_SECONDS, max(.01, max_seconds))
        self.root.mkdir(parents=True, exist_ok=True)
        self.active = None
        self._thread = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        with db.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS workflow_local_runs(
                id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,payload_hash TEXT NOT NULL,
                workflow_id TEXT NOT NULL,task_id INTEGER NOT NULL,status TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,receipt_json TEXT NOT NULL)''')

    def source_bytes(self):
        source = confined(Path('H:/NEXEN'), self.source)
        raw = source.read_bytes()
        if len(raw) > 1000000 or sha(raw) != SOURCE_SHA256:
            raise ValueError('Source 78 changed after review. Review and pin its new version before running.')
        workflow = json.loads(raw.decode('utf-8-sig'))
        if [(n.get('name'), n.get('type')) for n in workflow.get('nodes', [])] != list(NODE_INVENTORY):
            raise ValueError('Reviewed node inventory does not match.')
        if workflow.get('active') or any(n.get('credentials') or n.get('disabled') for n in workflow['nodes']):
            raise ValueError('Only the reviewed inactive and uncredentialed graph is supported.')
        return raw

    def task_id(self):
        rows = self.db.rows("SELECT r.id FROM hub_requests r JOIN task_details d ON d.request_id=r.id WHERE d.seed_key=?", ('workflow-card:' + CARD_ID,))
        if len(rows) != 1:
            raise ValueError('Save the Source 78 preparation task before running its local draft.')
        return int(rows[0]['id'])

    def default_packet(self):
        path = confined(self.root, self.root / 'CURRENT-DRAFT-INPUT.json')
        if not path.is_file():
            raise ValueError('The current reviewed draft input packet has not been saved yet.')
        if path.stat().st_size > MAX_INPUT:
            raise ValueError('The draft input packet exceeds its size limit.')
        return validate_packet(json.loads(path.read_text(encoding='utf-8-sig')))

    def review(self):
        result = dict(supported_card=CARD_ID, adapter=ADAPTER, engine_scope=ENGINE_SCOPE,
            source_sha256=SOURCE_SHA256, max_runtime_seconds=self.max_seconds,
            native_n8n_execution=False, model_calls=0, paid_spend=0, enabled=False,
            source_path=str(self.source), permissions=PERMISSIONS, active_job=self.active,
            remaining_integration='Native n8n scheduler/dispatcher execution is a separate integration requirement.')
        try:
            self.source_bytes()
            if not self.node.is_file():
                raise ValueError('The pinned local Node runtime is unavailable.')
            result['task_id'] = self.task_id()
            packet = self.default_packet()
            result.update(enabled=True, packet=packet, input_sha256=sha(encoded(packet)),
                input_status='owner_entered' if packet['input_basis']['owner_confirmed'] else 'needs_owner_profile_confirmation',
                reason='Run validates and packages this saved draft locally. Owner approval and operational readiness are separate.')
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
            result['reason'] = str(error) if isinstance(error, ValueError) else 'The reviewed source, task, or input packet is unavailable.'
        return result

    def path(self, ident, filename='receipt.json'):
        if not re.fullmatch(r'[a-f0-9]{32}', str(ident)):
            raise HTTPException(404, 'Local workflow receipt not found.')
        return confined(self.root, self.root / 'runs' / ident / filename)

    def get(self, ident):
        self.path(ident)
        rows = self.db.rows('SELECT receipt_json FROM workflow_local_runs WHERE id=?', (ident,))
        if not rows:
            raise HTTPException(404, 'Local workflow receipt not found.')
        receipt = json.loads(rows[0]['receipt_json'])
        receipt['result_url'] = '/api/workflows/executions/' + ident + '/result' if receipt.get('result_sha256') else None
        return receipt

    def latest(self):
        rows = self.db.rows('SELECT id FROM workflow_local_runs WHERE workflow_id=? ORDER BY created_at DESC,id DESC LIMIT 1', (CARD_ID,))
        return self.get(rows[0]['id']) if rows else None

    def record(self, receipt, terminal=False):
        receipt['updated_at'] = now()
        if terminal:
            receipt['finished_at'] = receipt['updated_at']
        with self.db.connect() as c:
            c.execute('UPDATE workflow_local_runs SET status=?,updated_at=?,receipt_json=? WHERE id=?',
                      (receipt['status'], receipt['updated_at'], encoded(receipt), receipt['id']))
            if terminal:
                task = c.execute('SELECT status FROM hub_requests WHERE id=?', (receipt['task_id'],)).fetchone()
                if task:
                    outcome = 'Source 78 local draft receipt ' + receipt['id'] + ': ' + receipt['status'] + '. ' + ENGINE_SCOPE
                    c.execute('INSERT INTO task_history(request_id,old_status,new_status,outcome,created_at) VALUES(?,?,?,?,?)',
                              (receipt['task_id'], task[0], task[0], outcome, now()))
        save_json(self.path(receipt['id']), receipt)

    def prepare(self, request):
        if request.source_sha256 != SOURCE_SHA256:
            raise HTTPException(409, 'The reviewed source version changed. Refresh the card before running.')
        try:
            raw = self.source_bytes()
            packet = validate_packet(request.packet) if request.packet is not None else self.default_packet()
            if sha(encoded(packet)) != request.input_sha256:
                raise ValueError('The draft input changed after review. Refresh and review the current packet.')
            task_id = self.task_id()
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise HTTPException(409, str(error) if isinstance(error, ValueError) else 'The reviewed source/input is unavailable.') from None
        fingerprint = sha(encoded(dict(source_sha256=SOURCE_SHA256, packet=packet, task_id=task_id, adapter=ADAPTER)))
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT id,payload_hash FROM workflow_local_runs WHERE request_key=?', (request.request_key,)).fetchone()
            if prior:
                if prior[1] != fingerprint:
                    raise HTTPException(409, 'This request key belongs to different source/input content.')
                return self.get(prior[0])
            ident = uuid.uuid4().hex
            folder = self.path(ident).parent
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'source.json').write_bytes(raw)
            save_json(folder / 'input.json', packet)
            (folder / 'runner.cjs').write_text(RUNNER, encoding='utf-8', newline='')
            receipt = dict(id=ident, workflow_id=CARD_ID, task_id=task_id, request_key=request.request_key,
                adapter=ADAPTER, engine_scope=ENGINE_SCOPE, source_sha256=SOURCE_SHA256,
                input_sha256=sha(encoded(packet)), runner_sha256=sha(RUNNER), status='prepared',
                input_basis=packet['input_basis'], created_at=now(), updated_at=now(),
                source_workflow_status=None, accepted_stages=[], contract_trace=[], executed=False,
                native_n8n_execution=False, model_calls=0, paid_spend=0, external_actions=False,
                max_runtime_seconds=self.max_seconds, result_sha256=None, error=None)
            save_json(folder / 'receipt.json', receipt)
            c.execute('INSERT INTO workflow_local_runs VALUES(?,?,?,?,?,?,?,?,?)',
                (ident, request.request_key, fingerprint, CARD_ID, task_id, 'prepared', receipt['created_at'], receipt['updated_at'], encoded(receipt)))
        return self.get(ident)

    def start(self, ident):
        with self._lock:
            receipt = self.get(ident)
            if receipt['status'] != 'prepared':
                return receipt
            if self.active:
                raise HTTPException(409, 'One local workflow draft is already running.')
            lease = SingleWriter(self.root)
            try:
                lease.__enter__()
            except RuntimeError:
                raise HTTPException(409, 'Another process owns the local draft worker.') from None
            # Reread after acquiring the interprocess lease to prevent duplicate runs.
            receipt = self.get(ident)
            if receipt['status'] != 'prepared':
                lease.__exit__()
                return receipt
            self.active = ident
            self._cancel.clear()
            receipt['status'] = 'running'
            receipt['started_at'] = now()
            self.record(receipt)
            self._thread = threading.Thread(target=self._run, args=(receipt, lease), daemon=True)
            self._thread.start()
            return self.get(ident)

    def _checkpoint(self, folder, started):
        if self._cancel.is_set() or (folder / 'cancel.requested').exists():
            raise InterruptedError('Local draft cancelled. No external action occurred.')
        if time.monotonic() - started > self.max_seconds:
            raise TimeoutError('Local draft exceeded its maximum runtime.')

    def _run(self, receipt, lease):
        started = time.monotonic()
        process = None
        folder = self.path(receipt['id']).parent
        try:
            self._checkpoint(folder, started)
            self.source_bytes()
            if sha((folder / 'source.json').read_bytes()) != SOURCE_SHA256 or sha((folder / 'runner.cjs').read_bytes()) != sha(RUNNER):
                raise ValueError('The prepared source or reviewed runner was modified.')
            packet = validate_packet(json.loads((folder / 'input.json').read_text(encoding='utf-8')))
            if sha(encoded(packet)) != receipt['input_sha256']:
                raise ValueError('The prepared input packet was modified.')
            temporary = folder / 'temp'
            temporary.mkdir(exist_ok=True)
            system = os.environ.get('SystemRoot', 'C:/Windows')
            environment = {'SystemRoot': system, 'WINDIR': system, 'TEMP': str(temporary), 'TMP': str(temporary),
                           'PATH': str(self.node.parent) + os.pathsep + str(Path(system) / 'System32')}
            process = subprocess.Popen([str(self.node), '--max-old-space-size=96', str(folder / 'runner.cjs')],
                cwd=folder, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            while True:
                self._checkpoint(folder, started)
                try:
                    _, stderr = process.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise ValueError('Source contract rejected this draft: ' + stderr.decode('utf-8', errors='replace')[:1100])
            self._checkpoint(folder, started)
            self.source_bytes()
            output = folder / 'runner-result.json'
            if not output.is_file() or output.stat().st_size > MAX_RESULT:
                raise ValueError('No bounded local result was produced.')
            native = json.loads(output.read_text(encoding='utf-8'))
            result = native['result']
            if result.get('permissions') != PERMISSIONS or result.get('status') not in ('ready_for_operator_review', 'awaiting_manual_chatgpt_response'):
                raise ValueError('Source contract returned an unexpected state or permission set.')
            if [x['node'] for x in native['trace']] != [x[0] for x in NODE_INVENTORY]:
                raise ValueError('The reviewed node contract trace is incomplete.')
            status = ('needs_manual_response' if result['status'] == 'awaiting_manual_chatgpt_response' else
                      'draft_ready' if packet['input_basis']['owner_confirmed'] else 'needs_owner_profile_confirmation')
            wrapped = dict(schema='nexen.source78.local-draft.v1', receipt_id=receipt['id'], task_id=receipt['task_id'],
                engine_scope=ENGINE_SCOPE, adapter=ADAPTER, source_sha256=SOURCE_SHA256, input_sha256=receipt['input_sha256'],
                input_basis=packet['input_basis'], operational_state='needs_owner_profile_confirmation' if not packet['input_basis']['owner_confirmed'] else 'owner_review_required',
                source_result=result, native_n8n_execution=False, model_calls=0, external_actions=False, paid_spend=0)
            save_json(folder / 'result.json', wrapped)
            receipt.update(status=status, executed=True, source_workflow_status=result['status'],
                accepted_stages=result.get('accepted_stages', []), contract_trace=native['trace'],
                next_stage=result.get('next_stage'), runtime=native['runtime'], result_sha256=sha((folder / 'result.json').read_bytes()),
                result_scope='A locally validated draft package; no owner profile approval, buyer, send, sale, or revenue is inferred.')
        except InterruptedError as error:
            receipt.update(status='cancelled', error=str(error))
        except (ValueError, TimeoutError) as error:
            receipt.update(status='failed', error=str(error)[:1400])
        except Exception as error:
            receipt.update(status='failed', error='Local draft adapter failed (' + type(error).__name__ + '). No external action occurred.')
        finally:
            try:
                if process and process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
                if process:
                    if process.stdout: process.stdout.close()
                    if process.stderr: process.stderr.close()
                receipt['duration_seconds'] = round(time.monotonic() - started, 3)
                self.record(receipt, terminal=True)
            finally:
                self.active = None
                lease.__exit__()

    def cancel(self, ident):
        with self._lock:
            receipt = self.get(ident)
            if receipt['status'] == 'running':
                self.path(ident, 'cancel.requested').write_text(now(), encoding='utf-8')
                if self.active == ident:
                    self._cancel.set()
            elif receipt['status'] == 'prepared':
                receipt.update(status='cancelled', error='Cancelled before local validation.')
                self.record(receipt, terminal=True)
            return self.get(ident)

    def result(self, ident):
        receipt = self.get(ident)
        if not receipt.get('result_sha256'):
            raise HTTPException(409, 'This run has no verified result artifact.')
        raw = self.path(ident, 'result.json').read_bytes()
        if len(raw) > MAX_RESULT or sha(raw) != receipt['result_sha256']:
            raise HTTPException(409, 'The saved result changed; inspect its receipt before using it.')
        return json.loads(raw)

    def recover(self):
        try:
            with SingleWriter(self.root):
                for row in self.db.rows("SELECT id FROM workflow_local_runs WHERE status='running'"):
                    receipt = self.get(row['id'])
                    receipt.update(status='interrupted', error='The previous worker stopped. No automatic retry was made.')
                    self.record(receipt, terminal=True)
        except RuntimeError:
            pass

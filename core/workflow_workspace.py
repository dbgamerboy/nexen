"""Evidence-backed workflow cards. Reading a definition never executes it.

Only owned H: sources are inspected. n8n databases are immutable backup reads;
the only mutation is a canonical Tracker preparation task. No credential table,
execution payload, node parameter, live n8n API, or imported command is exposed.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).resolve().parent
ROOT = Path('H:/NEXEN')
NO_RUN = 'A reviewed NEXEN execution adapter and an accepted input/output check are required. This card currently supports local preparation.'
NO_STOP = 'No running job is owned by this card and no verified stop adapter is connected.'
SOURCE_ROLES = {'video': 'VIDEO · faithful source method', 'userstack': 'USER-STACK · NEXEN adaptation'}
PAIRED_ASSETS = Path('workflows/instagram-reconstruction')
INTEGRATION_INDEX = Path('config/instagram-workflow-integrations.json')
WORKSPACES = (
    ('money', 'Money plan and cost review', 'Review costs, opportunities, evidence, and the next business task.', '/money', 'Saved cost inputs and a concrete offer to review.'),
    ('agents', 'Prepare an agent handoff', 'Create a cited handoff linked to one shared NEXEN task.', '/agents', 'A bounded task and a chosen target tool.'),
    ('voice', 'MARVIN voice workspace', 'Open the existing local voice controls and their current readiness.', '/voice', 'A working microphone and verified local speech adapters.'),
    ('photos', 'Photo to task', 'Review an image and connect its result to a tracked task.', '/photos', 'An owner-selected image and a verified local vision adapter.'),
    ('intake', 'Source intake and review', 'Review captured sources, tools, and workflow candidates.', '/intake-desk', 'Source evidence and the method to be reviewed.'),
    ('music', 'Music production workspace', 'Open the existing release and production workspace.', '/music-render', 'Owned source material and the production adapters shown in the workspace.'),
)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def clean(value, limit=1200):
    """Metadata only; conceal common embedded secret assignments if present."""
    value = str(value or '')
    value = re.sub(r'(?i)\b(api[_ -]?key|access[_ -]?token|password|secret|authorization)\s*[:=]\s*[^\s,;]+', r'\1=[redacted]', value)
    value = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{15,}|AIza[A-Za-z0-9_-]{20,})\b', '[redacted]', value)
    return value[:limit]


def graph_hash(wf):
    """ID/order/layout independent equality; preserve every executable parameter."""
    nodes = [{k: v for k, v in n.items() if k not in ('id', 'position')}
             for n in wf.get('nodes', []) if isinstance(n, dict)]
    return digest(dict(nodes=sorted(nodes, key=lambda x: str(x.get('name', ''))),
                       connections=wf.get('connections', {}), settings=wf.get('settings', {})))


def card_base(ident, name, purpose, family, status='draft'):
    return dict(id=ident, name=clean(name, 240) or 'Untitled workflow', purpose=clean(purpose),
                family=family, status=status, source_ids=[], roles=[], aliases=[], provenance=[],
                prerequisites=[], nodes=[], graph_hashes=[], n8n_ids=[], task_ids=[],
                last_execution=None, last_result=None, availability='Saved definition; execution unverified',
                source_method='', workspace_url=None, editor_url=None, recorded_active=False,
                variant_conflict=False, category=None, variant=None, source_shortcode=None,
                required_software=[], required_credentials=[], launch_ready=False,
                launch_state='blocked_setup', workflow_asset_path=None)


class DraftBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(default='', max_length=2000)


class WorkflowWorkspace:
    def __init__(self, db=None, root=ROOT, app_root=BASE, reel_assets_root=None):
        self.db, self.root, self.app_root = db, Path(root).resolve(), Path(app_root).resolve()
        self.reel_assets_root = Path(reel_assets_root or (self.app_root / 'data' / 'reel-assets')).resolve()
        self._cache = None
        self._cache_time = 0
        self._lock = threading.Lock()
        self._json_cache = {}
        self.execution = None

    def owned(self, path):
        path = Path(path).resolve()
        if not (path.is_relative_to(self.root) or path.is_relative_to(self.app_root)):
            raise ValueError('Source outside the allowed workspace')
        return path

    def read(self, path):
        path = self.owned(path)
        stat = path.stat()
        if stat.st_size > 32 * 1024 * 1024:
            raise ValueError('Source exceeds metadata read limit')
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        cached = self._json_cache.get(path)
        if cached and cached[0] == fingerprint:
            return cached[1]
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        self._json_cache[path] = (fingerprint, payload)
        return payload

    def _build(self):
        cards, errors, counts = {}, [], Counter()
        graph_index, id_index = {}, {}
        recovery = self.root / 'recovery'
        source_root = self.root / 'reels-finish'
        reconciliation = recovery / 'source-82-reconciliation-20260927'

        def failed(label, exc):
            errors.append(dict(source=label, error=type(exc).__name__,
                               detail='Metadata unavailable or invalid; coverage is incomplete.'))

        def add_definition(wf, path, scope, preferred=None, source=None, role=None):
            if not isinstance(wf, dict) or not isinstance(wf.get('nodes'), list):
                raise ValueError('Not an n8n workflow')
            graph = graph_hash(wf)
            native_id = str(wf.get('id') or '')
            metadata = wf.get('meta', {}).get('nexen', {}) if isinstance(wf.get('meta'), dict) else {}
            if not isinstance(metadata, dict):
                metadata = {}
            role_name = str(metadata.get('role', '')).lower().replace('-', '')
            source_number = metadata.get('source_id')
            canonical_key = 'source-%02d-%s' % (int(source_number), role_name) if str(source_number).isdigit() else None
            if not preferred and canonical_key in cards:
                preferred = canonical_key
            # Explicit source roles win; exact graph or native ID supplies aliases.
            catalog_id = str(metadata.get('catalog_id') or '')
            ident = preferred or catalog_id or id_index.get(native_id) or graph_index.get(graph)
            ident = ident or ('n8n-' + native_id if native_id else 'definition-' + graph[:24])
            card = cards.setdefault(ident, card_base(ident, wf.get('name'),
                wf.get('description') or wf.get('name'), 'source82' if source else 'n8n'))
            if graph not in card['graph_hashes']:
                card['graph_hashes'].append(graph)
            card['variant_conflict'] = len(card['graph_hashes']) > 1
            graph_index.setdefault(graph, ident)
            if native_id:
                id_index.setdefault(native_id, ident)
                if native_id not in card['n8n_ids']:
                    card['n8n_ids'].append(native_id)
                alias = 'n8n:' + native_id
                if alias not in card['aliases']:
                    card['aliases'].append(alias)
            card['provenance'].append(dict(kind=scope, path=str(path), graph_sha256=graph,
                                          name=clean(wf.get('name'), 240), native_id=native_id or None))
            if source and source not in card['source_ids']:
                card['source_ids'].append(source)
            if role and role not in card['roles']:
                card['roles'].append(role)
            if not card['nodes']:
                card['nodes'] = [dict(name=clean(n.get('name'), 150), type=clean(n.get('type'), 140),
                                     disabled=bool(n.get('disabled'))) for n in wf['nodes'] if isinstance(n, dict)]
            credential_types = sorted({str(k) for n in wf['nodes'] if isinstance(n, dict)
                                       for k in (n.get('credentials') or {})})
            if credential_types:
                card['prerequisites'].append('Resolve these credential types in the owner editor: ' + ', '.join(credential_types) + '.')
                card['required_credentials'] = [dict(type=name, name=name,
                    state='missing_or_unverified') for name in credential_types]
            if scope == 'nexen_workflow_asset' and catalog_id:
                card.update(family='source82', status='blocked', category=clean(metadata.get('category'), 100),
                    variant=clean(metadata.get('variant'), 40), source_shortcode=clean(metadata.get('source_shortcode'), 40),
                    required_software=[dict(name=clean(x.get('name'),120), category=clean(x.get('category'),80),
                        state=clean(x.get('state'),80), reason=clean(x.get('reason'),300), setup_url=clean(x.get('setup_url'),500))
                        for x in metadata.get('required_software',[]) if isinstance(x,dict)],
                    required_credentials=[dict(type=clean(x.get('type'),120),name=clean(x.get('name'),120),
                        state='missing_or_unverified', reason=clean(x.get('reason'),300))
                        for x in metadata.get('required_credentials',[]) if isinstance(x,dict)],
                    launch_ready=bool(metadata.get('launch_ready',False)),
                    launch_state=clean(metadata.get('launch_state') or 'blocked_setup',80),
                    workflow_asset_path=str(path))
                if card['source_shortcode'] and card['source_shortcode'] not in card['aliases']:
                    card['aliases'].append('instagram:' + card['source_shortcode'])
                for software in card['required_software']:
                    if software['state'] not in ('verified_ready','configured'):
                        card['prerequisites'].append(f"Software setup: {software['name']} — {software['state']}. {software['reason']}")
                for credential in card['required_credentials']:
                    card['prerequisites'].append(f"Credential missing/unverified: {credential['name']} ({credential['type']}).")
                card['prerequisites'].append('Native n8n launch adapter is not connected; Start remains blocked until a tested trigger contract and workflow ID are configured.')
                card['availability'] = 'Paired Instagram workflow asset; inactive export is staged for review, not running.'
                card['source_ids'] = sorted(set(card['source_ids'] + [int(x) for x in metadata.get('source_numbers',[]) if str(x).isdigit()]))
                card['source_method'] = clean(metadata.get('method'), 400)
            if any(n.get('disabled') for n in wf['nodes'] if isinstance(n, dict)):
                card['prerequisites'].append('Review disabled nodes and endpoint placeholders before execution.')
            if scope == 'established_local_backup':
                card['recorded_active'] = card['recorded_active'] or bool(wf.get('active'))
                card['availability'] = 'Present in the established local backup; current live state not queried'
            elif card['availability'].startswith('Saved'):
                card['availability'] = 'Definition inspected locally; inactive draft or preview only'
            return card

        # Latest checkpoint supplies all 82 IDs, including evidence-only exceptions.
        source_rows = []
        checkpoint = None
        try:
            candidates = sorted(reconciliation.glob('SOURCE-82-PROGRESS-CHECKPOINT-*.json'),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            checkpoint = candidates[0] if candidates else reconciliation / 'SOURCE-82-RECONCILED-BASELINE-20260927.json'
            payload = self.read(checkpoint)
            source_rows = payload['rows']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed('82-source checkpoint', exc)
        for row in source_rows:
            try:
                source = int(row['source_id'])
                folder = self.owned(row.get('h_source_folder') or source_root / ('source-%02d' % source))
                if not folder.is_relative_to(source_root.resolve()):
                    raise ValueError('Untrusted source folder')
                definitions = sorted(folder.glob('workflow*.json'))
                represented = []
                for path in definitions:
                    role = 'userstack' if re.search(r'user.?stack|adapt', path.stem, re.I) else 'video' if 'video' in path.stem else path.stem
                    ident = 'source-%02d-%s' % (source, role)
                    try:
                        card = add_definition(self.read(path), path, 'canonical_source_definition', ident, source, role)
                        card['name'] = clean(row.get('method') or card['name'], 200) + ' · ' + SOURCE_ROLES.get(role, 'Additional method')
                        represented.append(card)
                        counts['canonical_source_definitions'] += 1
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        failed(str(path), exc)
                if not represented:
                    ident = 'source-%02d-evidence' % source
                    classification = row.get('classification', '')
                    status = 'evidence_only' if classification in ('non_workflow', 'tool_inventory', 'tool_promotion', 'source_claims_only') else 'blocked'
                    card = cards.setdefault(ident, card_base(ident, row.get('method'),
                        'Source evidence is represented here; no canonical executable method is verified.', 'source82', status))
                    card['source_ids'] = [source]
                    card['availability'] = 'No canonical workflow definition found'
                    represented.append(card)
                for card in represented:
                    card['source_method'] = clean(row.get('method'))
                    card['purpose'] = clean(row.get('method')) or card['purpose']
                    card['source_classification'] = clean(row.get('classification'), 100)
                    card['source_review'] = clean(row.get('a_d_review_status') or row.get('coverage_status'), 160)
                    card['prerequisites'].extend(filter(None, [clean(row.get('next_action') or row.get('exact_next_piece')),
                        clean(row.get('gemini_specific_blocker')), clean(row.get('account_or_rights_gates'))]))
                    card['provenance'].append(dict(kind='source_checkpoint', path=str(checkpoint), source_id=source))
                    card['aliases'].append('source:%02d' % source)
                counts['source_rows'] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failed('82-source row', exc)

        # One latest immutable backup, then the staging package: never enumerate snapshots.
        backup = self.root / 'backups/n8n-pre-f-repair-20260927/database.sqlite'
        backup_stamp = None
        try:
            receipt = self.read(backup.with_name('BACKUP-RECEIPT.json'))
            backup_stamp = receipt.get('created_at_local')
            path = self.owned(backup)
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as c:
                c.row_factory = sqlite3.Row
                for item in c.execute('SELECT id,name,nodes,connections,settings,active FROM workflow_entity ORDER BY id'):
                    wf = dict(item)
                    for key in ('nodes', 'connections', 'settings'):
                        wf[key] = json.loads(wf[key] or ('[]' if key == 'nodes' else '{}'))
                    add_definition(wf, backup, 'established_local_backup')
                    counts['established_local_definitions'] += 1
                # Read status/time only, never execution_data or credentials_entity.
                for item in c.execute('SELECT e.id,e.workflowId,e.status,e.startedAt,e.stoppedAt FROM execution_entity e JOIN (SELECT workflowId,max(id) id FROM execution_entity GROUP BY workflowId) latest ON latest.id=e.id'):
                    ident = id_index.get(str(item['workflowId']))
                    if ident:
                        cards[ident]['last_execution'] = dict(id=str(item['id']), status=clean(item['status'], 80),
                            started_at=item['startedAt'], stopped_at=item['stoppedAt'], evidence_at=backup_stamp,
                            scope='Historical n8n execution in the backup; output payload and revenue not verified')
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            failed('Established local n8n backup', exc)

        packages = (
            (recovery / 'n8n-localhost-clean-20260926/NEXEN-LOCAL-IMPORT-20260927.json', 'staging_package'),
            (recovery / 'exported-only-dry-import-20260927/EXPORTED-ONLY-SAFE-INACTIVE.json', 'export_draft_package'),
        )
        for path, scope in packages:
            try:
                payload = self.read(path)
                if not isinstance(payload, list):
                    raise ValueError('Invalid definition package')
                for wf in payload:
                    add_definition(wf, path, scope)
                    counts[scope + '_definitions'] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failed(scope, exc)
        for path in sorted((self.app_root / 'workflows').glob('*.json')):
            try:
                add_definition(self.read(path), path, 'nexen_workflow_asset')
                counts['nexen_assets'] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failed(str(path), exc)
        paired_root = self.owned(self.app_root / PAIRED_ASSETS)
        if paired_root.is_dir():
            for path in sorted(paired_root.rglob('*.json')):
                if path.name in ('registry.json','integrations.json','PAIRS.json'):
                    continue
                try:
                    add_definition(self.read(path), path, 'nexen_workflow_asset')
                    counts['paired_instagram_assets'] += 1
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    failed(str(path), exc)

        # Preview IDs come from the proof's two imported packages and backup.
        try:
            proof = self.read(recovery / 'n8n-owner-preview-20260927/PROOF.json')
            if proof.get('passed') and proof.get('graphs_match'):
                preview_ids = {alias for card in cards.values() for alias in card['n8n_ids']
                               if any(p['kind'] in ('established_local_backup', 'export_draft_package') for p in card['provenance'])}
                additions = self.read(recovery / 'n8n-localhost-clean-20260926/NEXEN-ADDITIONS-ONLY-13-20260927.json')
                preview_ids.update(str(w['id']) for w in additions)
                for card in cards.values():
                    match = next((ident for ident in card['n8n_ids'] if ident in preview_ids), None)
                    if match:
                        card['editor_url'] = 'http://127.0.0.1:5695/workflow/' + quote(match, safe='')
                        card['editor_note'] = 'Owner preview on this PC, recorded ' + str(proof.get('checked_at_utc', '')) + '. Preview may require sign-in; current service availability is not probed.'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed('n8n preview mapping', exc)

        # DB rows are canonical proposals, not verified programs. Merge exact repeats only.
        proposal_ids = {}
        if self.db:
            try:
                for row in self.db.rows('SELECT id,name,objective,executor,status,source_file_id FROM workflows ORDER BY id'):
                    ident = 'proposal-' + digest([row.get('name'), row.get('objective'), row.get('executor')])[:24]
                    card = cards.setdefault(ident, card_base(ident, row.get('name'), row.get('objective'), 'proposal', 'proposal'))
                    alias = 'nexen:' + str(row['id'])
                    card['aliases'].append(alias)
                    card['provenance'].append(dict(kind='nexen_workflow_record', workflow_id=row['id'],
                        source_file_id=row.get('source_file_id'), saved_status=clean(row.get('status'), 80)))
                    card['availability'] = 'Saved NEXEN proposal; compilation is preparation only'
                    card['prerequisites'] = ['Review the original source, inputs, outputs, and a real executor before running this proposal.']
                    proposal_ids[int(row['id'])] = ident
                    counts['nexen_proposal_rows'] += 1
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                failed('NEXEN workflow records', exc)
        for path in sorted((self.app_root / 'data/generated_workflows').glob('*.json')):
            try:
                wf = self.read(path)
                workflow_id = int(wf.get('workflow_id', -1))
                ident = proposal_ids.get(workflow_id) or 'proposal-' + digest([wf.get('name'), wf.get('objective'), wf.get('executor')])[:24]
                card = cards.setdefault(ident, card_base(ident, wf.get('name'), wf.get('objective'), 'proposal', 'proposal'))
                card['provenance'].append(dict(kind='generated_proposal', path=str(path), workflow_id=workflow_id))
                alias = 'nexen:' + str(workflow_id)
                if alias not in card['aliases']:
                    card['aliases'].append(alias)
                counts['generated_proposal_files'] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failed(str(path), exc)
        # Reuse intake's existing privacy filter; never expose hidden source cards.
        try:
            from intake_workspace import IntakeWorkspace
            intake = IntakeWorkspace(root=self.root / 'intake/phone-20260913',
                                     repo_root=self.root / 'intake/catalog-20260913',
                                     expansion_root=self.root / 'intake/mobi-expansion-20260913')
            inventory = intake.inventory()
            for row in inventory['workflows']:
                ident = 'intake-' + digest(str(row['id']))[:24]
                card = cards.setdefault(ident, card_base(ident, row['title'],
                    'Review this captured workflow idea against its original source before implementing it.', 'intake', 'proposal'))
                card.update(workspace_url='/intake-desk', availability='OCR candidate available for source review',
                    source_method='Captured source candidate; method fidelity is unverified.',
                    prerequisites=['Review the source image and method, then specify inputs, outputs, and an executor.'],
                    aliases=['intake:' + str(row['id'])], provenance=[dict(kind='visible_intake_candidate',
                    source_id=row['source']['id'], title=clean(row['source']['title'], 240), route='/intake-desk')])
                counts['intake_candidate_rows'] += 1
            counts['private_intake_sources_hidden'] = inventory['private_sources_hidden']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed('Existing intake workflow candidates', exc)
        for key, name, purpose, url, prerequisite in WORKSPACES:
            ident = 'workspace-' + key
            card = cards.setdefault(ident, card_base(ident, name, purpose, 'workspace', 'workspace'))
            card.update(workspace_url=url, availability='Existing NEXEN workspace; adapter readiness is shown there',
                        prerequisites=[prerequisite], provenance=[dict(kind='code_owned_workspace', route=url)])

        if self.db:
            try:
                task_rows = self.db.rows("SELECT r.id,r.status,r.created_at,d.seed_key,d.next_step,(SELECT outcome FROM task_history h WHERE h.request_id=r.id ORDER BY h.id DESC LIMIT 1) outcome FROM hub_requests r JOIN task_details d ON d.request_id=r.id WHERE d.seed_key LIKE 'workflow-card:%'")
                for row in task_rows:
                    ident = row['seed_key'][len('workflow-card:'):]
                    if ident in cards:
                        cards[ident]['task_ids'].append(row['id'])
                        cards[ident]['last_result'] = dict(kind='preparation_task', task_id=row['id'],
                            status=clean(row['status'], 80), created_at=row['created_at'],
                            outcome=clean(row.get('outcome'), 2000),
                            summary='Saved preparation task. Its status is not evidence that the workflow executed.')
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                failed('Workflow preparation task links', exc)
        if self.execution and 'source-78-userstack' in cards:
            readiness = self.execution.review()
            cards['source-78-userstack']['local_execution'] = {
                k: v for k, v in readiness.items() if k != 'packet'}
            cards['source-78-userstack']['local_execution']['latest'] = self.execution.latest()
        self.add_reel_asset_cards(cards, errors)
        for card in cards.values():
            card['prerequisites'] = list(dict.fromkeys(card['prerequisites']))
            if card['variant_conflict']:
                card['prerequisites'].insert(0, 'Definition variants differ. Review the listed graph hashes before selecting a version.')
            if card['recorded_active']:
                card['status'] = 'recorded_active'
            card['actions'] = self.actions(card)
            card['provenance_count'] = len(card['provenance'])
            card['alias_count'] = len(card['aliases'])
        items = sorted(cards.values(), key=lambda c: ({'workspace': 0, 'source82': 1, 'n8n': 2, 'reel': 3, 'intake': 4, 'proposal': 5}[c['family']], min(c['source_ids'] or [999]), c['name'].lower(), c['id']))
        return dict(schema='nexen.workflow-cards.v1', checked_at=stamp(), cards=items,
            summary=dict(cards=len(items), families=dict(Counter(c['family'] for c in items)),
                states=dict(Counter(c['status'] for c in items)), **dict(counts)),
            coverage=dict(source_ids=sorted({s for c in items for s in c['source_ids']}),
                expected_source_rows=82, checkpoint=str(checkpoint) if checkpoint else None,
                backup_recorded_at=backup_stamp, cloud_inventory_verified=False, cloud_workflow_total=None,
                live_n8n_queried=False, errors=errors,
                identity='Canonical source role first; explicit n8n IDs and exact graph aliases. Exact NEXEN proposal repeats share a card.',
                limits=['The n8n Cloud inventory is missing; its total remains unknown.',
                        'Backup activity and execution timestamps are historical evidence.',
                        'Canonical H: source definitions refresh on reload. Upstream archive copies are not separate cards.',
                        'Private intake sources stay hidden. Unreviewed source-ingestion queues are not claimed as understood workflows.',
                        'A compiled proposal, static audit, or preview import does not verify execution or revenue.']),
            categories=sorted({c['category'] for c in items if c.get('category')}),
            executed=False, paid_requests=0)

    def add_reel_asset_cards(self, cards, errors):
        """Expose bundle-backed reel workflows in this canonical catalog."""
        if not self.reel_assets_root.is_dir():
            return
        for bundle in self.reel_assets_root.iterdir():
            if not bundle.is_dir() or not re.fullmatch(r'[a-f0-9]{24}', bundle.name):
                continue
            try:
                metadata = json.loads((bundle / 'metadata.json').read_text(encoding='utf-8'))
                preview = json.loads((bundle / 'preview.json').read_text(encoding='utf-8'))
                if metadata.get('asset_id') != bundle.name or preview.get('workflow_id') != bundle.name:
                    raise ValueError('Reel asset identity does not match its bundle.')
                ident = bundle.name
                card = cards.setdefault(ident, card_base(ident, preview.get('title'),
                    preview.get('one_line_purpose'), 'reel', metadata.get('lifecycle', 'captured')))
                card.update(status=metadata.get('lifecycle', 'captured'), workspace_url='/reel-assets',
                    availability='Bundle-backed paired reel skill and workflow; see evidence and run status in Reel assets.',
                    source_method=preview.get('why', ''),
                    prerequisites=['Review the source, skill, inputs and workflow placeholders before any execution.'],
                    workflow_asset=dict(asset_id=ident, skill_id=preview.get('skill_id'),
                        workflow_id=preview.get('workflow_id'), executable=bool(preview.get('executable')),
                        source_url=preview.get('source_url'), preview_url='/reel-assets'))
                card['roles'] = ['reel_skill', 'reel_workflow']
                card['aliases'] = list(dict.fromkeys(card['aliases'] + [
                    'reel-skill:' + ident, 'reel-workflow:' + ident,
                    'source:' + str(metadata.get('source_id', 'unknown'))]))
                card['provenance'].append(dict(kind='reel_asset_bundle', path=str(bundle),
                    source_id=metadata.get('source_id'), asset_id=ident))
                if not preview.get('executable'):
                    card['prerequisites'].append('Workflow is reference-only; compile and review a cited workflow draft first.')
                elif preview.get('workflow_kind') == 'executable_skeleton':
                    card['prerequisites'].append('Generated workflow steps are placeholders; replace and validate adapters before use.')
            except (OSError, ValueError, TypeError) as exc:
                errors.append(dict(source='reel asset bundle', error=type(exc).__name__,
                                   detail='Bundle metadata unavailable or invalid; catalog coverage is incomplete.'))

    def actions(self, card):
        ident = card['id']
        local = card.get('local_execution') or {}
        latest = local.get('latest') or {}
        result = [dict(id='details', label='Details', enabled=True, kind='detail'),
            dict(id='setup', label='Software & credentials', enabled=True, kind='integrations'),
            dict(id='draft', label='Open preparation task' if card['task_ids'] else 'Prepare manual draft', enabled=self.db is not None,
                 kind='draft', reason='' if self.db else 'Connect the canonical NEXEN task database to save a preparation task.'),
            dict(id='run', label='Start workflow' if card.get('workflow_asset_path') else ('Run local draft' if local else 'Run workflow'),
                 enabled=bool(local.get('enabled')) if local else bool(card.get('launch_ready')),
                 kind='run' if (local or card.get('workflow_asset_path')) else 'disabled',
                 reason=local.get('reason') or ('' if card.get('launch_ready') else 'Start is blocked: required software/adapters, credentials and a verified n8n launch route are not ready.') or NO_RUN),
            dict(id='results', label='Results', enabled=bool(latest or card['last_execution'] or card['last_result']), kind='results',
                 reason='' if latest or card['last_execution'] or card['last_result'] else 'No execution receipt or saved preparation task is recorded for this card.'),
            dict(id='editor', label='Workflow editor', enabled=bool(card['editor_url']), kind='link', href=card['editor_url'],
                 reason=card.get('editor_note') if card['editor_url'] else 'No verified preview editor ID is mapped. Prepare a task to review and implement this definition.')]
        if card['workspace_url']:
            result.insert(0, dict(id='workspace', label='Open workspace', enabled=True, kind='link', href=card['workspace_url']))
        if card['recorded_active']:
            result.append(dict(id='stop', label='Stop workflow', enabled=False, kind='disabled', reason=NO_STOP + ' The active flag is from a backup.'))
        if latest.get('status') in ('prepared', 'running'):
            result.append(dict(id='cancel', label='Cancel local draft', enabled=True, kind='run',
                               reason='Cancels this owned local draft; no native n8n scheduler is controlled.'))
        return result

    def integrations(self):
        path = self.owned(self.app_root / INTEGRATION_INDEX)
        try:
            value = self.read(path)
        except (OSError, ValueError, TypeError):
            return dict(schema='nexen.workflow-integrations.v1', categories=[], integrations=[],
                        error='Integration setup index is unavailable; no dependency is reported ready.')
        return value

    def catalog(self, force=False, compact=False):
        with self._lock:
            if force or self._cache is None or time.monotonic() - self._cache_time > 15:
                self._cache = self._build()
                self._cache_time = time.monotonic()
            result = self._cache
        if not compact:
            return result
        return dict(result, cards=[{k: v for k, v in c.items() if k not in ('provenance', 'nodes', 'aliases', 'graph_hashes')}
                                   for c in result['cards']])

    def detail(self, ident):
        card = next((c for c in self.catalog()['cards'] if c['id'] == ident), None)
        if card is None:
            raise HTTPException(404, 'Workflow card not found.')
        return card

    def resolve_action(self, ident, action):
        card = self.detail(ident)
        result = next((a for a in card['actions'] if a['id'] == action), None)
        if result is None:
            raise HTTPException(404, 'This card does not support that action.')
        if not result['enabled']:
            raise HTTPException(409, result['reason'])
        return result

    def create_draft(self, ident, note=''):
        self.resolve_action(ident, 'draft')
        card = self.detail(ident)
        from task_tracking import Tracker, TaskCreate
        tracker = Tracker(self.db)
        body = TaskCreate(text='Prepare workflow: ' + card['name'], next_step=clean(
            'Workflow card: ' + ident + '\nPurpose: ' + card['purpose'] + '\nRequirements: ' +
            ' '.join(card['prerequisites']) + ('\nOwner note: ' + note if note else '') +
            '\nReview evidence and produce a local draft. No account action or workflow execution is implied.', 2000))
        task_id = tracker.create(body, seed_key='workflow-card:' + ident)
        self._cache_time = 0
        return dict(workflow_id=ident, task_id=task_id, task_url='/tasks',
                    next_url='/next?task_id=' + str(task_id), task=tracker.get(task_id),
                    executed=False, state='preparation_saved', paid_requests=0)


def register(app, db=None, workspace=None):
    """Call inside the existing private/authenticated NEXEN app registration."""
    from pc_control import validate_request
    desk = workspace or WorkflowWorkspace(db)
    if workspace is None and db is not None:
        from workflow_execution import WorkflowExecution
        desk.execution = WorkflowExecution(db)
        desk.execution.recover()

    def executor(workflow_id='source-78-userstack'):
        if workflow_id != 'source-78-userstack' or desk.execution is None:
            raise HTTPException(409, 'No reviewed local execution adapter is connected for this workflow.')
        return desk.execution

    from workflow_execution import RunRequest

    @app.get('/api/workflows/{workflow_id}/execution')
    def execution_review(workflow_id: str, request: Request):
        validate_request(request)
        return executor(workflow_id).review()

    @app.post('/api/workflows/{workflow_id}/run')
    def run_local_draft(workflow_id: str, body: RunRequest, request: Request):
        validate_request(request, mutation=True)
        service = executor(workflow_id)
        receipt = service.prepare(body)
        receipt = service.start(receipt['id'])
        desk._cache_time = 0
        return receipt

    @app.get('/api/workflows/executions/{ident}')
    def execution_receipt(ident: str, request: Request):
        validate_request(request)
        return executor().get(ident)

    @app.get('/api/workflows/executions/{ident}/result')
    def execution_result(ident: str, request: Request):
        validate_request(request)
        return JSONResponse(executor().result(ident), headers={'Cache-Control': 'no-store'})

    @app.post('/api/workflows/executions/{ident}/cancel')
    def cancel_local_draft(ident: str, request: Request):
        validate_request(request, mutation=True)
        receipt = executor().cancel(ident)
        desk._cache_time = 0
        return receipt

    @app.get('/workflows', response_class=HTMLResponse)
    def page(request: Request):
        validate_request(request)
        return HTMLResponse((desk.app_root / 'workflows.html').read_text(encoding='utf-8'),
                            headers={'Cache-Control': 'no-store'})

    @app.get('/api/workflows/catalog')
    def catalog(request: Request, refresh: bool = False):
        validate_request(request)
        return JSONResponse(desk.catalog(force=refresh, compact=True), headers={'Cache-Control': 'no-store'})

    @app.get('/api/workflows/integrations')
    def integrations(request: Request):
        validate_request(request)
        return JSONResponse(desk.integrations(), headers={'Cache-Control': 'no-store'})

    @app.get('/api/workflows/{workflow_id}')
    def details(workflow_id: str, request: Request):
        validate_request(request)
        return JSONResponse(desk.detail(workflow_id), headers={'Cache-Control': 'no-store'})

    @app.post('/api/workflows/{workflow_id}/draft')
    def draft(workflow_id: str, body: DraftBody, request: Request):
        validate_request(request, mutation=True)
        return desk.create_draft(workflow_id, body.note)

    return desk

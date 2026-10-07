"""Shared, local memory entry point for NEXEN model calls and browser tools."""
from pathlib import Path
import threading
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from memory_bridge import SharedMemory

BASE = Path(__file__).resolve().parent
VAULT = Path('F:/NEXEN_MEMORY')
_sync_lock = threading.Lock()


def shared_memory():
    return SharedMemory(BASE / 'data/exports/exports.sqlite3', vault=VAULT,
                        knowledge_db=BASE / 'data/nexen.db')


def context_for(query, task_type='code', pool=None, max_chars=6000, limit=5):
    from knowledge_flow import flow_for
    packet = shared_memory().build_context(query, task_type=task_type,
                                          max_chars=max_chars, limit=limit, pool=pool)
    packet['flow'] = flow_for(packet)
    return packet


def enrich_prompt(prompt, task_type='code', pool=None):
    packet = context_for(prompt, task_type, pool)
    return prompt_with_context(prompt, packet)


def prompt_with_context(prompt, packet):
    context = packet.get('text', '')
    if not context:
        raise ValueError('Shared memory returned no context. Check the memory index.')
    from knowledge_flow import answer_instructions
    return (answer_instructions() + '\n\nNEXEN SHARED CONTEXT\n' + context +
            '\nEND SHARED CONTEXT\n\nCURRENT REQUEST\n' + prompt)


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=12000)
    task_type: Literal['code', 'workflow', 'automation'] = 'code'
    pool: Literal['all','commerce','music','life','game','voice','automation','engineering'] | None = None


class RecursiveLearningCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    parent_id: str | None = Field(default=None, max_length=100)
    owner: str | None = Field(default=None, max_length=100)
    module: str | None = Field(default=None, max_length=100)


class NovelLearningReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)


class RecursiveLearningRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidates: list[RecursiveLearningCandidate] = Field(min_length=1, max_length=50)
    novel_learning_scope: list[str] = Field(default_factory=list, max_length=50)
    novel_learning_references: list[NovelLearningReference] = Field(default_factory=list, max_length=50)
    max_depth: int = Field(default=3, ge=0, le=3)


class RecursiveLearningFeedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_text: str = Field(min_length=1, max_length=12000)
    decision: Literal['approve', 'exclude']
    reason_code: Literal['owner_approved', 'novel_overlap', 'duplicate', 'conflict',
                         'insufficient_provenance', 'other'] = 'other'


def register(app):
    @app.get('/memory-pools', response_class=HTMLResponse)
    def memory_workspace():
        return (BASE/'memory-pools.html').read_text(encoding='utf-8')

    @app.post('/api/memory/context')
    def memory_context(body: ContextRequest):
        return context_for(body.query, body.task_type,body.pool)

    @app.post('/api/memory/recursive-learning/preview')
    def recursive_learning_preview(body: RecursiveLearningRequest):
        from recursive_learning import load_feedback, run_recursive_learning

        candidates = [item.model_dump() for item in body.candidates]
        by_id = {item['candidate_id']: item for item in candidates}
        if len(by_id) != len(candidates):
            raise HTTPException(422, 'candidate_id values must be unique.')
        children = {ident: [] for ident in by_id}
        roots = []
        for item in candidates:
            parent = item.get('parent_id')
            if parent is None:
                roots.append(item)
            elif parent not in by_id:
                raise HTTPException(422, 'Every parent_id must refer to a submitted candidate.')
            else:
                children[parent].append(item)
        if not roots:
            raise HTTPException(422, 'At least one root candidate is required.')

        query = ' '.join(item['text'] for item in candidates)[:12000]
        packet = shared_memory().build_context(query, task_type='code', max_chars=6000, limit=5)
        references = [dict(source_id=item.reference_id, text=item.text)
                      for item in body.novel_learning_references]
        database = BASE / 'data/nexen.db'
        configured_scope = (any(term.strip() for term in body.novel_learning_scope)
                            or any(item.text.strip() for item in body.novel_learning_references))
        result = run_recursive_learning(
            roots,
            expand=lambda item: children.get(item.get('candidate_id'), []),
            existing_items=packet.get('citations', []),
            novel_learning_items=references,
            novel_learning_scope=body.novel_learning_scope,
            scope_configured=configured_scope,
            feedback=load_feedback(database),
            max_depth=body.max_depth,
            max_candidates=min(50, len(candidates)),
        )
        visited = {item['candidate_id'] for item in result['candidates']}
        result['unevaluated_candidate_ids'] = sorted(set(by_id) - visited)
        result['scope_status'] = ('caller_supplied' if configured_scope
                                  else 'unavailable_fails_closed')
        result['retrieved_source_ids'] = [item.get('source_id') for item in packet.get('citations', [])
                                          if isinstance(item.get('source_id'), str)]
        result['warnings'] = packet.get('warnings', [])
        return result

    @app.post('/api/memory/recursive-learning/feedback')
    def recursive_learning_feedback(body: RecursiveLearningFeedback):
        from recursive_learning import record_feedback
        return record_feedback(BASE / 'data/nexen.db', body.candidate_text,
                               body.decision, reason_code=body.reason_code)

    @app.get('/api/memory/pools')
    def pools():
        from memory_pools import POOLS
        return {'pools':[{'id':key,'label':value['label']} for key,value in POOLS.items()],
                'storage':'Existing conversation, source-note, file-chunk and completion indexes; no duplicate knowledge database.',
                'context_route':'/api/memory/context','local_only':True}

    @app.post('/api/memory/sync')
    def sync_memory():
        if not _sync_lock.acquire(blocking=False):
            raise HTTPException(409, 'An Obsidian memory refresh is already running.')
        try:
            return shared_memory().sync_vault()
        finally:
            _sync_lock.release()

    @app.get('/api/memory/bridge')
    def memory_bridge_status():
        return {
            'vault': str(VAULT),
            'vault_exists': VAULT.is_dir(),
            'context_route': '/api/memory/context',
            'sync_route': '/api/memory/sync',
            'local_lab': 'attached',
            'model_router': 'attached',
            'external_harnesses': 'separate_adapter_required',
            'scope': 'Relevant indexed sources and selected current decisions; not every file on F:.',
            'egress': 'none',
        }

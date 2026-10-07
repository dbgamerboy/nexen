"""Read-only phone intake desk; register behind NEXEN's existing auth middleware.

Never forwards photos or OCR to a model. No task execution or file writes.
"""
from pathlib import Path
import json
import re
import stat
import hashlib
import threading
import time
from collections import OrderedDict, Counter
from urllib.parse import urlsplit
from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

PHONE_ROOT = Path('H:/NEXEN/intake/phone-20260913')
REPO_ROOT = Path('H:/NEXEN/intake/catalog-20260913')
EXPANSION_ROOT = Path('H:/NEXEN/intake/mobi-expansion-20260913')
PAGE = Path(__file__).with_name('intake-workspace.html')
SOURCE_ID = re.compile(r'^phone-[a-f0-9]{12}$')
CONTENT_ID = re.compile(r'^[a-f0-9]{64}$')
REVIEW_CATEGORIES = ('commerce', 'workflow', 'music', 'prompt')


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return value


def confined_file(root, candidate):
    """Require a real regular file below a real root, with no linked components."""
    root = Path(root).absolute()
    candidate = Path(candidate).absolute()
    if not candidate.is_relative_to(root):
        raise ValueError('Path is outside the intake root')
    for path in (candidate, *candidate.parents):
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Linked intake paths are not allowed')
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or not resolved.is_file():
        raise ValueError('Not a confined regular file')
    return resolved


class IntakeWorkspace:
    def __init__(self, root=PHONE_ROOT, repo_root=REPO_ROOT, page=PAGE, expansion_root=EXPANSION_ROOT, index_batch=64):
        self.root, self.repo_root, self.page = Path(root), Path(repo_root), Path(page)
        self.expansion_root = Path(expansion_root)
        self.index_batch = max(1, min(index_batch, 64))
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._lock = threading.RLock()
        self._metadata = {}
        self._index_cursor = 0

    def read(self, name, default, root=None):
        root = self.root if root is None else Path(root)
        path = root / name
        if not path.exists():
            return default
        path = confined_file(root, path)
        info = path.stat()
        if info.st_size > 12 * 1024 * 1024:
            raise ValueError('Intake catalog is too large')
        key = str(path)
        signature = (info.st_mtime_ns, info.st_size)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == signature:
                self._cache.move_to_end(key)
                return cached[1]
            with path.open('rb') as source:
                raw = source.read(12 * 1024 * 1024 + 1)
            if len(raw) > 12 * 1024 * 1024:
                raise ValueError('Intake catalog grew beyond its read limit')
            data = json.loads(raw.decode('utf-8-sig'))
            if cached: self._cache_bytes -= cached[2]
            self._cache[key] = (signature, data, len(raw))
            self._cache_bytes += len(raw)
            while self._cache_bytes > 32 * 1024 * 1024 or len(self._cache) > 24:
                _, removed = self._cache.popitem(last=False)
                self._cache_bytes -= removed[2]
            return data

    def expansion_manifest(self):
        manifest = self.read('manifest.json', {}, self.expansion_root)
        rows, content = manifest.get('sources', {}), manifest.get('content', {})
        if not isinstance(rows, dict) or not isinstance(content, dict):
            raise ValueError('Invalid expansion manifest')
        valid = {cid: value for cid, value in content.items()
                 if CONTENT_ID.fullmatch(cid) and isinstance(value, dict) and value.get('sha256') == cid}
        if len(valid) != len(content) or any(not isinstance(row, dict) for row in rows.values()):
            raise ValueError('Malformed source identity or metadata')
        return manifest, rows, valid

    def card_data(self, cid):
        path = confined_file(self.expansion_root / 'cards', self.expansion_root / 'cards' / (cid + '.json'))
        with path.open('rb') as source:
            raw = source.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024: raise ValueError('Source card exceeds the review limit')
        card = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(card, dict) or card.get('sha256') != cid:
            raise ValueError('Source card identity mismatch')
        return card, len(raw)

    def index_metadata(self, content):
        """Incrementally read bounded cards; cache classification, never raw OCR."""
        for cid in list(self._metadata):
            if cid not in content: del self._metadata[cid]
        ids = list(content)
        missing = [cid for cid in ids if cid not in self._metadata]
        refresh = ids[self._index_cursor:self._index_cursor + self.index_batch]
        candidates = list(dict.fromkeys(missing[:self.index_batch] + refresh))[:self.index_batch]
        consumed = 0
        reads = 0
        for cid in candidates:
            if consumed + 256 * 1024 > 2 * 1024 * 1024: break
            try:
                card, size = self.card_data(cid)
                consumed += size
                categories = card.get('categories', {})
                if not isinstance(categories, dict): categories = {}
                tools = card.get('tool_mentions', [])
                self._metadata[cid] = {'categories': [c for c in REVIEW_CATEGORIES if categories.get(c)],
                                       'tool_count': len(tools) if isinstance(tools, list) else 0,
                                       'classification_status': 'machine_candidates', 'updated': time.monotonic()}
            except (OSError, ValueError, TypeError, KeyError):
                # Missing/oversized/invalid cards are not classified or treated as reviewed.
                self._metadata[cid] = {'categories': [], 'tool_count': 0,
                                       'classification_status': 'card_unavailable', 'updated': time.monotonic()}
            reads += 1
        self._index_cursor = (self._index_cursor + self.index_batch) % max(1, len(ids))
        return {'cards_read_this_request': reads, 'card_bytes_this_request': consumed,
                'category_indexed': sum(v['classification_status'] == 'machine_candidates' for v in self._metadata.values()),
                'category_pending': len(content) - sum(v['classification_status'] == 'machine_candidates' for v in self._metadata.values()),
                'category_index_complete': len(content) == sum(v['classification_status'] == 'machine_candidates' for v in self._metadata.values())}

    @staticmethod
    def expansion_summary(manifest, sources, content):
        source_states = Counter(r.get('status', 'unknown') for r in sources.values() if isinstance(r, dict))
        content_states = Counter(c.get('ocr_status', 'pending') for c in content.values())
        # Review requires a distinct explicit evidence record; opening a card is not review completion.
        reviewed = sum(c.get('review_status') == 'reviewed' and bool(c.get('review_evidence')) for c in content.values())
        read = content_states['ocr_complete'] + content_states['ocr_complete_no_text']
        return {'observed_sources': len(sources), 'verified_source_records': source_states['accepted'],
                'source_records_pending': len(sources) - source_states['accepted'], 'unique_content': len(content),
                'machine_ocr_complete': read, 'ocr_with_text': content_states['ocr_complete'],
                'ocr_no_text': content_states['ocr_complete_no_text'], 'ocr_errors': content_states['ocr_error'],
                'transcription_pending': content_states['transcription_pending'],
                'ocr_pending': sum(v for k, v in content_states.items() if k not in {'ocr_complete', 'ocr_complete_no_text', 'transcription_pending', 'ocr_error'}),
                'reviewed_content': reviewed, 'unreviewed_content': len(content) - reviewed,
                'source_status': dict(source_states), 'updated_at': manifest.get('updated_at'),
                'worker_heartbeat_only': True, 'workflow_execution_verified': False}

    def expansion_inventory(self, category='money', offset=0, limit=24):
        if category not in {'money', 'all', 'workflow', 'music', 'prompt'} or not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError('Invalid expansion page')
        with self._lock:
            manifest, sources, content = self.expansion_manifest()
            indexing = self.index_metadata(content)
            wanted = 'commerce' if category == 'money' else category
            matching = []
            for cid, record in content.items():
                metadata = self._metadata.get(cid, {'categories': [], 'tool_count': 0, 'classification_status': 'not_indexed'})
                if category != 'all' and wanted not in metadata['categories']: continue
                matching.append({'id': cid, 'title': 'Source ' + cid[:10], 'kind': record.get('kind', 'unknown'),
                                 'ocr_status': record.get('ocr_status', 'pending'),
                                 'review_status': 'reviewed' if record.get('review_status') == 'reviewed' and record.get('review_evidence') else 'unreviewed',
                                 'categories': metadata['categories'], 'tool_mentions_count': metadata['tool_count'],
                                 'classification_status': metadata['classification_status'],
                                 'source_count': len(record.get('sources', [])),
                                 'legacy_reused': bool(record.get('reused_legacy')),
                                 'private_source': True, 'exclude_from_shared_prompt': True,
                                 'review_url': '/api/intake-desk/expansion/review/' + cid})
            matching.sort(key=lambda r: ('commerce' not in r['categories'], r['id']))
            return {'available': bool(manifest), 'summary': self.expansion_summary(manifest, sources, content), 'indexing': indexing,
                    'category': category, 'offset': offset, 'limit': limit,
                    'matched_in_current_index': len(matching), 'items': matching[offset:offset+limit],
                    'has_next': offset + limit < len(matching), 'next_offset': offset + limit if offset + limit < len(matching) else None,
                    'raw_ocr_included': False, 'mode': 'private_read_only_review', 'executed': False}

    def review(self, cid, reveal=False, source_offset=0, source_limit=25):
        if not CONTENT_ID.fullmatch(cid): raise HTTPException(404, 'Source not found')
        if not 0 <= source_offset <= 100000 or not 1 <= source_limit <= 50:
            raise ValueError('Invalid provenance page')
        _, _, content = self.expansion_manifest()
        record = content.get(cid)
        if not record: raise HTTPException(404, 'Source not found')
        result = {'id': cid, 'private_source': True, 'exclude_from_shared_prompt': True,
                  'cloud_export_allowed_by_default': False, 'raw_ocr_included': False,
                  'review_status': 'reviewed' if record.get('review_status') == 'reviewed' and record.get('review_evidence') else 'unreviewed', 'executed': False}
        if not reveal: return result
        card, _ = self.card_data(cid)
        refs = record.get('sources', [])
        if not isinstance(refs, list): raise ValueError('Invalid source provenance')
        provenance = []
        for ref in refs[source_offset:source_offset+source_limit]:
            if not isinstance(ref, dict) or not isinstance(ref.get('source_path'), str) or len(ref['source_path']) > 32768:
                raise ValueError('Invalid source provenance')
            provenance.append({'source_id': str(ref.get('source_id', '')), 'source_path': ref['source_path']})
        original = record.get('original_path', '')
        if not isinstance(original, str) or len(original) > 32768: raise ValueError('Invalid original path')
        text = card.get('exact_ocr_text', '')
        if not isinstance(text, str): raise ValueError('Invalid OCR text')
        result.update(raw_ocr_included=True, exact_ocr_text=text[:12000], text_truncated=len(text)>12000,
                      source_provenance=provenance, source_total=len(refs), source_offset=source_offset,
                      source_next_offset=source_offset+source_limit if source_offset+source_limit < len(refs) else None,
                      original_path=original, ocr_status=record.get('ocr_status'),
                      extraction_status='unreviewed_machine_extraction',
                      note='Machine OCR may contain errors. This local view does not mark review complete, forward a prompt, or execute a workflow.')
        return result

    def sources(self):
        manifest = self.read('manifest.json', {})
        sources = manifest.get('sources', [])
        if not isinstance(sources, list):
            raise ValueError('Invalid source manifest')
        return manifest, {r['source_id']: r for r in sources if isinstance(r, dict) and SOURCE_ID.fullmatch(str(r.get('source_id', '')))}

    @staticmethod
    def private(row):
        return bool(row.get('private_source') or row.get('exclude_from_shared_prompt'))

    def repositories(self):
        for filename in ('repositories.json', 'repository-inventory.json', 'github-repositories.json', 'repos.json', 'repo-inventory.json'):
            raw = self.read(filename, None, self.repo_root)
            if raw is None:
                continue
            rows = raw if isinstance(raw, list) else raw.get('repositories', raw.get('repos', raw.get('items', [])))
            result = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                url = safe_url(row.get('url') or row.get('github_url') or row.get('canonical_url'))
                name = str(row.get('repo') or row.get('name') or row.get('full_name') or '')
                if not url and re.fullmatch(r'[\w.-]+/[\w.-]+', name):
                    url = 'https://github.com/' + name
                if url:
                    result.append({'name': name or urlsplit(url).path.strip('/'), 'url': url,
                                   'status': str(row.get('status') or row.get('verification') or 'Catalogued source'),
                                   'description': str(row.get('description', ''))[:1000]})
            return result, 'loaded'
        return [], 'not_found'

    def inventory(self):
        manifest, all_sources = self.sources()
        visible = {sid: r for sid, r in all_sources.items() if not self.private(r)}
        def source(sid):
            row = visible[sid]
            return {'id': sid, 'title': row['source_name'], 'kind': row.get('kind'),
                    'status': row.get('ocr_status'),
                    'preview_url': '/api/intake-desk/preview/' + sid if row.get('preview_path') else None}
        tools = []
        seen_tools = set()
        reviewed = self.read('reviewed-software-cards.json', [])
        machine = self.read('software-cards.json', [])
        for card in [*reviewed, *machine]:
            sid = card.get('source_id')
            if sid not in visible:
                continue
            key = (sid, re.sub(r'[^a-z0-9]', '', str(card.get('name', '')).lower()))
            if key in seen_tools:
                continue
            seen_tools.add(key)
            tools.append({'id': str(card.get('id')), 'name': str(card.get('name', 'Tool mention')),
                          'url': safe_url(card.get('url')),
                          'quotes': card.get('exact_ocr_quotes', []),
                          'category': 'From screenshots',
                          'status': card.get('status', 'Source mention'), 'source': source(sid)})
        bookmarks = self.read('bookmarks-tools.json', {}, self.repo_root)
        bookmarks = bookmarks if isinstance(bookmarks, list) else bookmarks.get('bookmarks', [])
        bookmark_count = 0
        for card in bookmarks:
            url = safe_url(card.get('url'))
            if not url:
                continue
            bookmark_count += 1
            ident = 'bookmark-' + hashlib.sha256(url.encode()).hexdigest()[:16]
            tools.append({'id': ident, 'name': str(card.get('name') or url), 'url': url,
                          'quotes': [], 'category': str(card.get('category', 'Bookmarked tools')),
                          'status': 'Saved Chrome bookmark',
                          'source': {'id': ident, 'title': 'Chrome bookmarks', 'kind': 'bookmark', 'preview_url': None}})
        cards = self.read('cards.json', [])
        workflows = [{'id': c['id'], 'title': c['title'], 'quotes': c.get('workflow_quotes', []),
                      'status': 'OCR workflow candidate', 'source': source(c['source_id'])}
                     for c in cards if c.get('source_id') in visible and c.get('workflow_quotes')]
        best = self.read('best-pics.json', {}).get('items', [])
        photos = [{**source(r['source_id']), 'reason': r.get('selection_reason', '')}
                  for r in best if r.get('source_id') in visible]
        tips = []
        for card in [*self.read('reviewed-prompt-tips.json', []), *self.read('prompt-tips.json', [])]:
            sid = card.get('source_id')
            if sid in visible:
                tips.append({'id': card['id'], 'title': card.get('title', 'Prompt candidate'),
                             'quote': str(card.get('quote', '')), 'insert_text': str(card.get('insert_text') or card.get('quote', '')),
                             'status': card.get('status', 'unreviewed_ocr_candidate'), 'source': source(sid)})
        repos, catalog_status = self.repositories()
        return {'summary': manifest.get('summary', {}), 'private_sources_hidden': len(all_sources)-len(visible),
                'sources': [source(sid) for sid in visible], 'tools': tools, 'workflows': workflows,
                'photos': photos, 'prompt_tips': tips, 'repositories': repos, 'catalog_status': catalog_status,
                'bookmark_cards': bookmark_count,
                'mode': 'read_only', 'executed': False}

    def preview(self, source_id):
        if not SOURCE_ID.fullmatch(source_id):
            raise HTTPException(404, 'Preview not found')
        _, rows = self.sources()
        row = rows.get(source_id)
        if not row or self.private(row) or not row.get('preview_path'):
            raise HTTPException(404, 'Preview not found')
        try:
            path = confined_file(self.root / 'previews', row['preview_path'])
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                raise ValueError('Unsupported preview')
            return path
        except (OSError, ValueError):
            raise HTTPException(404, 'Preview not found') from None


def register(app, db=None, workspace=None):
    """Existing nexen_hub middleware must protect all these routes, as for other modules."""
    desk = workspace or IntakeWorkspace()

    @app.get('/intake-desk', response_class=HTMLResponse)
    def intake_page():
        return HTMLResponse(desk.page.read_text(encoding='utf-8'), headers={'Cache-Control': 'no-store'})

    @app.get('/api/intake-desk')
    def intake_inventory():
        try:
            return JSONResponse(desk.inventory(), headers={'Cache-Control': 'no-store'})
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Intake files are unavailable or invalid; originals are unchanged.') from None

    @app.get('/api/intake-desk/preview/{source_id}')
    def intake_preview(source_id: str):
        try:
            path = desk.preview(source_id)
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(404, 'Preview not found') from None
        return FileResponse(path, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/intake-desk/expansion')
    def expansion_inventory(category: str = Query('money', pattern='^(money|all|workflow|music|prompt)$'),
                            offset: int = Query(0, ge=0, le=100000), limit: int = Query(24, ge=1, le=100)):
        try:
            return JSONResponse(desk.expansion_inventory(category, offset, limit), headers={'Cache-Control': 'no-store'})
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'New intake metadata is unavailable. Originals and the existing worker are unchanged.') from None

    @app.get('/api/intake-desk/expansion/review/{content_id}')
    def expansion_review(content_id: str, reveal: bool = False,
                         source_offset: int = Query(0, ge=0, le=100000), source_limit: int = Query(25, ge=1, le=50)):
        try:
            return JSONResponse(desk.review(content_id, reveal, source_offset, source_limit),
                                headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'This source card is not ready for local review.') from None

    return desk

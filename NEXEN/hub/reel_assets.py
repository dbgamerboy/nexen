"""Reel investment assets: paired Claude skill + n8n workflow bundles built from an indexed YouTube source.

Every bundle keeps one canonical asset ID shared by its skill, workflow and preview
records. Generation is deterministic and offline: it only reorganizes evidence
already produced by youtube_memory (segments, and a compiled 'workflow' draft when
one exists). No cloud model call, no n8n execution and no fabricated revenue/ROI
data happen here.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from memory_bridge import redact, _reject_links

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'data' / 'reel-assets'
ID = re.compile(r'[a-f0-9]{24}')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def slugify(text, limit=48):
    slug = re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-')
    return (slug or 'reel')[:limit]


class CreateBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str | None = Field(default=None, min_length=24, max_length=24)
    source_url: str | None = Field(default=None, min_length=12, max_length=2048)
    title: str = Field(default='', max_length=240)
    creator: str | None = Field(default=None, max_length=240)
    source_date: str | None = Field(default=None, max_length=80)
    capture_date: str | None = Field(default=None, max_length=80)
    source_references: list[str] = Field(default_factory=list, max_length=10)
    transcript: str | None = Field(default=None, min_length=1, max_length=180000)
    coverage: str = Field(default='User-supplied transcript; completeness and wording not independently verified.', max_length=2000)
    evidence_images: list[str] = Field(default_factory=list, max_length=3)
    lesson: str = Field(default='', max_length=3000)
    why: str = Field(default='', max_length=2000)
    when_to_use: list[str] = Field(default_factory=list, max_length=6)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    examples: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def source_shape(self):
        if self.source_id:
            if self.source_url or self.transcript or self.evidence_images:
                raise ValueError('Use either an indexed source_id or supplied source material, not both.')
        elif not self.source_url or not self.transcript:
            raise ValueError('Provide an indexed source_id or both source_url and transcript.')
        return self


def asset_id_for(source_id):
    return sha('reel-asset-v1\n' + source_id)[:24]


def supplied_source(body):
    try:
        parts = urlsplit(body.source_url)
        allowed = {'instagram.com', 'www.instagram.com', 'tiktok.com', 'www.tiktok.com',
                   'youtube.com', 'www.youtube.com', 'youtu.be'}
        valid = (parts.scheme == 'https' and parts.hostname in allowed and not parts.username and
                 not parts.password and parts.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, 'Source must be an HTTPS Instagram, TikTok or YouTube URL.')
    ident = sha('reel-source-v1\n' + body.source_url + '\n' + sha(body.transcript))[:24]
    segments = []
    for line in body.transcript.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r'^\[(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\]\s*(.*)$', line)
        segments.append({'start': float(match.group(1)) if match else None,
                         'end': float(match.group(2)) if match and match.group(2) else None,
                         'text': redact(match.group(3) if match else line),
                         'ref': 'segment-%03d' % (len(segments) + 1)})
    if not segments:
        raise HTTPException(422, 'Transcript contains no usable text lines.')
    return {'id': ident, 'url': body.source_url, 'title': redact(body.title or 'Untitled short-form source'),
            'creator': redact(body.creator) if body.creator else None, 'source_date': body.source_date,
            'status': 'ready', 'transcript_origin': 'user_supplied_transcript', 'transcript_sha256': sha(body.transcript),
            'segments': segments, 'coverage': redact(body.coverage), 'drafts': {}, 'artifacts': {},
            'lesson': redact(body.lesson), 'why': redact(body.why),
            'when_to_use': [redact(x) for x in body.when_to_use],
            'assumptions': [redact(x) for x in body.assumptions],
            'examples': [redact(x) for x in body.examples],
            'provenance': {'retrieved_at': None, 'source_url': body.source_url,
                           'source_creator': redact(body.creator) if body.creator else None,
                           'source_date': body.source_date, 'capture_date': body.capture_date,
                           'source_references': [redact(x) for x in body.source_references],
                           'transcript_supplied': True, 'external_source': True}}


def draft_steps(source):
    draft = (source.get('drafts') or {}).get('workflow')
    steps = draft.get('steps') if isinstance(draft, dict) else None
    return draft, (steps or [])


def build_skill_markdown(source, asset_id, draft, steps):
    title = redact(source['title'])
    slug = slugify(title)
    guide = (source.get('drafts') or {}).get('guide')
    when_lines = '\n'.join('- ' + redact(item) for item in source.get('when_to_use', [])) or '\n'.join(
        '- ' + redact(step.get('title', 'Step'))[:120] + ': ' + redact(step.get('instruction', ''))[:400]
        + ' (source ' + ', '.join(step.get('source_refs', [])) + ')'
        for step in steps
    ) or '- Not yet determined. Compile a workflow draft from this source first (POST /api/youtube-memory/sources/{id}/compile).'
    why = redact(draft['summary']) if draft else (redact(guide['summary']) if guide else (redact(source.get('why')) or 'Not yet reviewed; add a source-grounded rationale.'))
    refs = sorted({ref for step in steps for ref in step.get('source_refs', [])})
    one_line = re.sub(r'\s+', ' ', redact(draft['title']) if draft else (redact(guide['title']) if guide else (redact(source.get('lesson')) or title))).strip()[:200]
    status = 'converted' if steps else 'captured'
    return '''---
name: reel-{slug}
description: {one_line}. Use when reviewing or rebuilding the workflow captured from this source video.
metadata:
  asset_id: {asset_id}
  source_id: {source_id}
  source_url: {source_url}
  status: {status}
---

# {title}

## Why this exists
{why}

## When to use
{when_lines}

## How
{lesson}

Review any extracted step against current primary evidence before acting. Workflow nodes are placeholders;
nothing here executes automatically.

## Assumptions and examples
- Assumptions: {assumptions}
- Examples: {examples}

## Source
- URL: {source_url}
- Transcript SHA-256: {transcript_sha256}
- Coverage: {coverage}
- Cited segments: {refs}
'''.format(slug=slug, one_line=one_line, asset_id=asset_id, source_id=source['id'], source_url=source['url'],
           status=status, title=title, why=why, when_lines=when_lines,
           lesson=redact(source.get('lesson') or 'No separate lesson was recorded.'),
           assumptions='; '.join(redact(x) for x in source.get('assumptions', [])) or 'not recorded',
           examples='; '.join(redact(x) for x in source.get('examples', [])) or 'none recorded',
           transcript_sha256=source['transcript_sha256'], coverage=redact(source.get('coverage', '')),
           refs=', '.join(refs) if refs else 'none yet (no compiled draft)')


def build_workflow(source, asset_id, draft, steps):
    reason = ('No compiled workflow draft is available for this source yet.' if not steps else
              'Compiled steps are represented by NoOp placeholders. A reviewed adapter and verification are required.')
    nodes = [{'id': 'trigger', 'name': 'Manual Trigger', 'type': 'n8n-nodes-base.manualTrigger',
              'typeVersion': 1, 'position': [0, 300], 'parameters': {}}]
    connections, previous = {}, 'Manual Trigger'
    for index, step in enumerate(steps, start=1):
        name = ('Step %d: %s' % (index, redact(step.get('title', 'Step'))))[:64]
        nodes.append({'id': 'step%d' % index, 'name': name, 'type': 'n8n-nodes-base.noOp', 'typeVersion': 1,
                      'position': [index * 240, 300], 'parameters': {},
                      'notes': redact(step.get('instruction', ''))[:500], 'notesInFlow': True})
        connections.setdefault(previous, {'main': [[]]})['main'][0].append({'node': name, 'type': 'main', 'index': 0})
        previous = name
    return {
        'name': redact(source['title'])[:120], 'nodes': nodes, 'connections': connections, 'active': False,
        'settings': {'executionOrder': 'v1'}, 'status': 'reference_only', 'executable': False,
        'asset_id': asset_id, 'skill_id': asset_id, 'workflow_id': asset_id, 'source_id': source['id'],
        'reason': reason,
        'next_action': 'Replace placeholders with reviewed nodes, test with representative input, then record evaluation evidence.',
        'meta': {'nexen_asset_id': asset_id, 'skill_id': asset_id, 'workflow_id': asset_id,
                 'source_id': source['id'], 'execution': 'not_executed',
                 'inputs': [], 'outputs': [],
                 'note': 'NoOp placeholder nodes document each cited step. Replace a node with a reviewed adapter before treating this as a real automation; importing this file into n8n does not run anything by itself.'},
    }


def build_diagram(source, steps):
    title = redact(source['title']).replace('"', "'")[:60]
    lines = ['flowchart TD', '  src["Source: %s"] --> skill["Skill: reviewed steps"]' % title]
    previous = 'skill'
    if steps:
        for index, step in enumerate(steps, start=1):
            node = 'step%d' % index
            label = redact(step.get('title', 'Step')).replace('"', "'")[:60]
            lines.append('  %s --> %s["%s"]' % (previous, node, label))
            previous = node
        lines.append('  %s --> workflow["n8n workflow (reference placeholders)"]' % previous)
    else:
        lines.append('  skill --> workflow["n8n workflow: reference only, not compiled"]')
    return '\n'.join(lines)


def build_diagram_svg(steps):
    """Small cached diagram fallback rendered with stdlib SVG; no new JS dependency."""
    labels = ['Source', 'Claude skill'] + [redact(s.get('title', 'Step'))[:22] for s in steps[:4]] + ['n8n workflow']
    if len(labels) > 6:
        labels = labels[:5] + ['n8n workflow']
    box_w, gap, left = 110, 16, 12
    width = max(360, left * 2 + len(labels) * box_w + (len(labels) - 1) * gap)
    bits = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d 76" role="img" aria-label="Source, skill, and workflow diagram">' % width,
            '<rect width="100%" height="76" rx="12" fill="#04101c"/>']
    for i, label in enumerate(labels):
        x = left + i * (box_w + gap)
        if i:
            bits.append('<path d="M%d 38h12m-5-5 5 5-5 5" fill="none" stroke="#76b7df" stroke-width="2"/>' % (x - gap))
        bits.append('<rect x="%d" y="16" width="%d" height="44" rx="8" fill="#102c42" stroke="#65a8d1"/><text x="%d" y="42" text-anchor="middle" fill="#eaf2ff" font-family="sans-serif" font-size="11">%s</text>' % (x, box_w, x + box_w // 2, xml_escape(label)))
    bits.append('</svg>')
    return ''.join(bits)


def build_metadata(source, asset_id, executable, steps=None):
    lifecycle = 'converted' if steps else 'captured'
    origin = str(source.get('transcript_origin') or '')
    if origin in {'youtube_browser_caption', 'youtube_caption', 'youtube_caption_file'}:
        source_access, cost_type = 'public_youtube_caption', 'free_public_source'
    elif origin == 'youtube_browser_partial':
        source_access, cost_type = 'partial_public_youtube_caption', 'free_public_source'
    else:
        source_access, cost_type = 'user_supplied_transcript', 'unknown_user_supplied'
    return {
        'asset_id': asset_id, 'source_id': source['id'], 'lifecycle': lifecycle,
        'source_access': source_access, 'cost_type': cost_type, 'implementation_effort': 'unknown_not_estimated',
        'revenue_relevance': 'unverified_no_revenue_claimed',
        'reusability': 'single_source_template' if executable else 'not_yet_reusable',
        'roi_notes': 'Not measured. No revenue or performance has been recorded for this asset.',
        'source_url': source['url'], 'source_title': redact(source['title']),
        'captured_at': (source.get('provenance') or {}).get('retrieved_at'),
        'transcript_sha256': source['transcript_sha256'],
        'creator': source.get('creator') or (source.get('provenance') or {}).get('creator'),
        'source_date': source.get('source_date') or (source.get('provenance') or {}).get('published_at'),
        'capture_date': (source.get('provenance') or {}).get('capture_date'),
        'related_source_references': (source.get('provenance') or {}).get('source_references', []),
        'source_transcript': {'source_id': source['id'], 'sha256': source['transcript_sha256'],
                              'origin': source.get('transcript_origin'), 'coverage': source.get('coverage'),
                              'path': 'source/transcript.md'},
        'examples': [redact(x) for x in source.get('examples', [])[:3]],
        'verification_notes': [source.get('coverage') or 'Source coverage not recorded.',
                               'No workflow execution or evaluation has been recorded.'],
        'evaluation': {'status': 'not_tested', 'results': []},
        'lifecycle_status': {'captured': True, 'converted': bool(steps), 'tested': False, 'active': False, 'retired': False},
        'tags': [urlsplit(source['url']).hostname or 'short-form', 'converted'] if steps else
                [urlsplit(source['url']).hostname or 'short-form', 'uncompiled'],
        'created_at': now(), 'updated_at': now(),
    }


def build_preview(source, asset_id, metadata, diagram, executable, steps, draft, screenshots=None):
    guide = (source.get('drafts') or {}).get('guide')
    when_to_use = ([redact(item)[:200] for item in source.get('when_to_use', [])][:6]
                   or [redact(step.get('title', 'Step'))[:120] for step in steps][:6]
                   or ([redact(guide['title'])[:120]] if guide else ['Not yet determined; record a source-grounded use case.']))
    return {
        'id': asset_id, 'skill_id': asset_id, 'workflow_id': asset_id,
        'title': redact(source['title']),
        'one_line_purpose': (redact(draft['title']) if draft else (redact(guide['title']) if guide else (redact(source.get('lesson')) or redact(source['title']))))[:200],
        'why': redact(draft['summary']) if draft else (redact(guide['summary']) if guide else (redact(source.get('why')) or 'Not yet reviewed. Add a source-grounded rationale.')),
        'when_to_use': when_to_use,
        'skill_id': asset_id, 'workflow_id': asset_id,
        'what_happens_if_run': ('Manual trigger starts only NoOp placeholders; no external action occurs.'
                                if steps else 'Nothing runs. The paired workflow is reference-only until a draft is compiled and reviewed.'),
        'diagram': diagram[:1200],
        'screenshots': (screenshots or [])[:3], 'examples': metadata.get('examples', [])[:3],
        'creator': metadata.get('creator'), 'source_date': metadata.get('source_date'),
        'status': metadata['lifecycle'], 'tags': metadata['tags'], 'executable': executable,
        'source_url': source['url'],
        'actions': {
            'open_skill': '/api/reel-assets/%s/skill' % asset_id,
            'run_workflow': None,
            'open_workflow': '/api/reel-assets/%s/workflow' % asset_id,
            'expand_preview': '/api/reel-assets/%s' % asset_id,
            'view_source': source['url'],
        },
    }


class ReelAssetRegistry:
    def __init__(self, db, youtube_service, root=ROOT):
        self.db, self.youtube, self.root = db, youtube_service, Path(root)
        _reject_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _row(self, asset_id):
        if not ID.fullmatch(asset_id):
            raise HTTPException(404, 'Reel asset not found.')
        bundle = self.root / asset_id
        _reject_links(bundle)
        if not bundle.is_dir():
            raise HTTPException(404, 'Reel asset not found.')
        try:
            metadata = json.loads((bundle / 'metadata.json').read_text(encoding='utf-8'))
            preview = json.loads((bundle / 'preview.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise HTTPException(409, 'Reel asset metadata is unavailable or invalid.') from exc
        if metadata.get('asset_id') != asset_id or preview.get('id') != asset_id:
            raise HTTPException(409, 'Reel asset identity does not match its bundle directory.')
        return {'id': asset_id, 'source_id': metadata.get('source_id'), 'title': preview.get('title', ''),
                'lifecycle': metadata.get('lifecycle', 'captured'),
                'executable': int(bool(preview.get('executable'))), 'bundle_path': str(bundle),
                'metadata': metadata, 'preview': preview,
                'created_at': metadata.get('created_at', ''), 'updated_at': metadata.get('updated_at', '')}

    def build_bundle(self, source):
        asset_id = asset_id_for(source['id'])
        draft, steps = draft_steps(source)
        converted = bool(steps)
        executable = False
        diagram = build_diagram(source, steps)
        diagram_svg = build_diagram_svg(steps)
        metadata = build_metadata(source, asset_id, executable, steps)
        screenshots = []
        for key, path in (source.get('artifacts') or {}).items():
            if 'frame' in str(key).lower() and isinstance(path, str):
                screenshots.append({'path': path, 'caption': 'Source evidence frame'})
            if len(screenshots) == 3:
                break
        preview = build_preview(source, asset_id, metadata, diagram, executable, steps, draft, screenshots)
        skill_md = build_skill_markdown(source, asset_id, draft, steps)
        workflow = build_workflow(source, asset_id, draft, steps)
        return asset_id, executable, diagram, diagram_svg, metadata, preview, skill_md, workflow, converted

    def create(self, body):
        body = CreateBody.model_validate(body)
        source = self.youtube.get(body.source_id, full=True) if body.source_id else supplied_source(body)
        if source['status'] != 'ready':
            raise HTTPException(409, 'Import and index a YouTube transcript before creating a reel asset.')
        asset_id, executable, diagram, diagram_svg, metadata, preview, skill_md, workflow, converted = self.build_bundle(source)
        bundle_dir = self.root / asset_id
        _reject_links(bundle_dir)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / 'screenshots').mkdir(exist_ok=True)
        (bundle_dir / 'SKILL.md').write_text(skill_md, encoding='utf-8')
        (bundle_dir / 'workflow.json').write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding='utf-8')
        (bundle_dir / 'diagram.mmd').write_text(diagram, encoding='utf-8')
        (bundle_dir / 'diagram.svg').write_text(diagram_svg, encoding='utf-8')
        (bundle_dir / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        (bundle_dir / 'preview.json').write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding='utf-8')
        (bundle_dir / 'source').mkdir(exist_ok=True)
        image_root = Path(r'H:\NEXEN\intake').resolve()
        preview_images = []
        for index, raw_path in enumerate(body.evidence_images if not body.source_id else [], start=1):
            image_path = Path(raw_path)
            _reject_links(image_path)
            try:
                resolved = image_path.resolve(strict=True)
                resolved.relative_to(image_root)
            except (OSError, ValueError, RuntimeError):
                raise HTTPException(422, 'Evidence images must be existing files under H:\\NEXEN\\intake.') from None
            if not resolved.is_file() or resolved.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'} or resolved.stat().st_size > 12 * 1024 * 1024:
                raise HTTPException(422, 'Evidence images must be JPEG, PNG or WebP files up to 12 MiB.')
            name = 'evidence-%02d%s' % (index, resolved.suffix.lower())
            shutil.copyfile(resolved, bundle_dir / 'screenshots' / name)
            preview_images.append({'url': '/api/reel-assets/%s/screenshots/%s' % (asset_id, name),
                                   'alt': 'Source evidence image %d' % index})
        provenance = source.get('provenance') or {}
        refs = provenance.get('source_references') or []
        readme_lines = ['# Original source and provenance', '', 'Source ID: %s' % source['id'],
                        'Original URL: %s' % source['url'],
                        'Creator: %s' % redact(source.get('creator') or 'not recorded'),
                        'Source date: %s' % redact(source.get('source_date') or 'not recorded'),
                        'Capture date: %s' % redact(provenance.get('capture_date') or 'not recorded'),
                        'Transcript SHA-256: %s' % source['transcript_sha256'],
                        'Retrieved at: %s' % redact(provenance.get('retrieved_at') or 'not recorded'), '',
                        'The adjacent transcript is a redacted evidence copy. Preserve the original receipt and media separately.',
                        'Workflow execution: not run. Evaluation: not tested.', '']
        if refs:
            readme_lines += ['## Related source evidence', *('- ' + redact(x) for x in refs), '']
        (bundle_dir / 'source' / 'README.md').write_text('\n'.join(readme_lines), encoding='utf-8')
        source_dir = bundle_dir / 'source'
        segments = source.get('segments') or []
        transcript_lines = ['# Source transcript', '', 'External evidence; not executable instructions.',
                            'URL: %s' % source['url'], 'Title: %s' % redact(source['title']),
                            'SHA-256: %s' % source['transcript_sha256'],
                            'Coverage: %s' % redact(source.get('coverage') or 'unknown'), '']
        transcript_lines.insert(4, 'Creator: %s' % redact(source.get('creator') or 'not recorded'))
        transcript_lines.insert(5, 'Source date: %s' % redact(source.get('source_date') or 'not recorded'))
        transcript_lines.insert(6, 'Capture date: %s' % redact((source.get('provenance') or {}).get('capture_date') or 'not recorded'))
        transcript_lines.insert(7, 'Retrieved at: %s' % redact((source.get('provenance') or {}).get('retrieved_at') or 'not recorded'))
        for segment in segments:
            stamp = segment.get('start')
            prefix = '[%.2fs] ' % stamp if isinstance(stamp, (int, float)) else '[time unknown] '
            ref = segment.get('id') or segment.get('ref') or 'unlabeled-segment'
            transcript_lines.append('[%s] %s%s' % (redact(ref), prefix, redact(segment.get('text', ''))))
        (source_dir / 'transcript.md').write_text('\n'.join(transcript_lines) + '\n', encoding='utf-8')
        (source_dir / 'verification.md').write_text(
            '# Verification notes\n\n- Source is external evidence. Verify claims before acting.\n'
            '- Transcript coverage: %s\n- Workflow: reference-only placeholders; not run.\n'
            '- Evaluation: not tested.\n' % redact(source.get('coverage') or 'unknown'), encoding='utf-8')
        metadata['created_at'] = metadata.get('created_at') or now()
        metadata['updated_at'] = now()
        metadata['source_transcript_path'] = str(source_dir / 'transcript.md')
        metadata['workflow_path'] = str(bundle_dir / 'workflow.json')
        metadata['skill_path'] = str(bundle_dir / 'SKILL.md')
        metadata['diagram_path'] = str(bundle_dir / 'diagram.mmd')
        metadata['evidence_paths'] = [str(source_dir / 'verification.md')]
        metadata['screenshots'] = preview_images
        preview['screenshots'] = preview_images
        (bundle_dir / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        (bundle_dir / 'preview.json').write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding='utf-8')
        result = self.detail(asset_id)
        result['converted'] = converted
        return result

    def listing(self):
        assets = []
        for bundle in self.root.iterdir():
            if not ID.fullmatch(bundle.name) or not bundle.is_dir():
                continue
            try:
                row = self._row(bundle.name)
            except HTTPException:
                continue
            assets.append(row['preview'])
        assets.sort(key=lambda item: item.get('created_at', ''), reverse=True)
        return {'assets': assets[:200], 'count': min(len(assets), 200)}

    def detail(self, asset_id):
        row = self._row(asset_id)
        bundle = Path(row['bundle_path'])
        return {
            'id': row['id'], 'source_id': row['source_id'], 'title': row['title'], 'lifecycle': row['lifecycle'],
            'executable': bool(row['executable']), 'created_at': row['created_at'], 'updated_at': row['updated_at'],
            'skill_markdown': (bundle / 'SKILL.md').read_text(encoding='utf-8'),
            'workflow': json.loads((bundle / 'workflow.json').read_text(encoding='utf-8')),
            'diagram_mermaid': (bundle / 'diagram.mmd').read_text(encoding='utf-8'),
            'diagram_svg': (bundle / 'diagram.svg').read_text(encoding='utf-8')
                if (bundle / 'diagram.svg').is_file() else '',
            'source_reference': (bundle / 'source' / 'README.md').read_text(encoding='utf-8')
                if (bundle / 'source' / 'README.md').is_file() else '',
            'source_transcript': (bundle / 'source' / 'transcript.md').read_text(encoding='utf-8')
                if (bundle / 'source' / 'transcript.md').is_file() else '',
            'verification_notes': (bundle / 'source' / 'verification.md').read_text(encoding='utf-8')
                if (bundle / 'source' / 'verification.md').is_file() else '',
            'metadata': row['metadata'],
            'preview': row['preview'],
        }

    def skill_markdown(self, asset_id):
        return self.detail(asset_id)['skill_markdown']

    def workflow_json(self, asset_id):
        return self.detail(asset_id)['workflow']


def register(app, db, youtube_service, root=ROOT):
    from pc_control import validate_request
    registry = ReelAssetRegistry(db, youtube_service, root=root)

    @app.get('/api/reel-assets')
    def listing(request: Request):
        validate_request(request)
        return registry.listing()

    @app.post('/api/reel-assets')
    def create(body: CreateBody, request: Request):
        validate_request(request, mutation=True)
        return registry.create(body)

    @app.get('/api/reel-assets/{asset_id}')
    def detail(asset_id: str, request: Request):
        validate_request(request)
        return registry.detail(asset_id)

    @app.get('/api/reel-assets/{asset_id}/skill', response_class=PlainTextResponse)
    def skill(asset_id: str, request: Request):
        validate_request(request)
        return registry.skill_markdown(asset_id)

    @app.get('/api/reel-assets/{asset_id}/workflow')
    def workflow(asset_id: str, request: Request):
        validate_request(request)
        return JSONResponse(registry.workflow_json(asset_id))

    @app.get('/api/reel-assets/{asset_id}/context')
    def context(asset_id: str, request: Request):
        """Return the skill before its paired workflow for MARVIN/NEXEN retrieval."""
        validate_request(request)
        detail = registry.detail(asset_id)
        return {'asset_id': detail['id'], 'sequence': ['skill', 'workflow'],
                'skill': {'id': detail['preview']['skill_id'], 'markdown': detail['skill_markdown']},
                'workflow': {'id': detail['preview']['workflow_id'], 'definition': detail['workflow'],
                             'invocation_allowed': bool(detail['workflow'].get('executable')),
                             'execution_status': detail['workflow'].get('status')},
                'purpose': detail['preview']['one_line_purpose'],
                'why': detail['preview']['why']}

    @app.get('/api/reel-assets/{asset_id}/diagram.svg')
    def diagram(asset_id: str, request: Request):
        validate_request(request)
        svg = registry.detail(asset_id)['diagram_svg']
        return Response(svg, media_type='image/svg+xml', headers={'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/reel-assets/{asset_id}/screenshots/{filename}')
    def screenshot(asset_id: str, filename: str, request: Request):
        validate_request(request)
        if not ID.fullmatch(asset_id) or not re.fullmatch(r'evidence-\d{2}\.(?:jpg|jpeg|png|webp)', filename):
            raise HTTPException(404, 'Evidence image not found.')
        path = registry.root / asset_id / 'screenshots' / filename
        _reject_links(path)
        if not path.is_file():
            raise HTTPException(404, 'Evidence image not found.')
        return FileResponse(path)

    @app.get('/reel-assets', response_class=HTMLResponse)
    def page(request: Request):
        validate_request(request)
        return PAGE

    return registry


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXEN &middot; Reel assets</title><style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;color:#eaf2ff;background:#061827}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 92% 0,#21577938,transparent 50%),#061827}
main{max-width:1200px;margin:auto;padding:32px 22px}a{color:#a7dfff}header{display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap}h1{font-size:34px;letter-spacing:-1px;margin:10px 0}p{color:#9fb9cf;line-height:1.6}
.glass{background:#d9e9ff0a;border:1px solid #def0ff21;border-radius:18px}
.toolbar{padding:16px;margin:18px 0;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button,input,select{font:inherit;color:inherit;background:#0b1326;border:1px solid #a8c7ff38;border-radius:10px;padding:9px 12px}
button{cursor:pointer;background:#b4dbff16}button:hover{background:#b4dbff30}button:disabled{opacity:.5}
.primary{background:#bddeff;color:#0d1e34}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:16px}
.card{position:relative;padding:18px}
.card:focus-within .hover{display:block}
.card:focus-within .hover{display:block}
.card b{font-size:17px}
.tag{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#a5d8ff}
.hover{display:none;position:absolute;left:0;right:0;top:100%;margin-top:8px;z-index:5;padding:16px;background:#0b1e30;border:1px solid #a8c7ff55;border-radius:14px;box-shadow:0 20px 40px #0006;max-height:min(70vh,540px);overflow:auto}
.card:hover .hover{display:block}
.examples{display:flex;gap:8px;overflow:auto;margin:8px 0}.examples img{height:76px;max-width:120px;object-fit:cover;border-radius:7px;border:1px solid #a8c7ff38}
.mini-diagram{display:block;width:100%;height:76px;object-fit:contain;object-position:left center;background:#04101c;border-radius:8px;margin:8px 0}
.hover pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:#9fc8e6;background:#04101c;padding:8px;border-radius:8px;max-height:120px;overflow:auto}
.hover .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.hover .actions a,.hover .actions button{font-size:11px;padding:6px 9px}
#modal{display:none;position:fixed;inset:0;background:#03101cd8;padding:30px;overflow:auto;z-index:20}
#modal .box{max-width:900px;margin:auto;background:#0b1e30;border:1px solid #a8c7ff55;border-radius:16px;padding:26px}
#modal pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#04101c;padding:12px;border-radius:10px}
small,.muted{color:#8dabc4}
</style><main>
<header><div><a href="/youtube-memory">&larr; YouTube memory</a> &middot; <a href="/workflows">Shared workflow catalog</a><h1>Reel investment assets</h1><p>Every useful research reel becomes a paired Claude skill + n8n workflow, both sharing one asset ID.</p></div></header>
<div class="toolbar glass"><label>Indexed YouTube source ID<input id="source-id" placeholder="24-char source ID (optional)" maxlength="24" style="width:260px"></label><details><summary>Or add a short-form source</summary><p><input id="source-url" placeholder="Original HTTPS reel URL" style="width:min(450px,80vw)"></p><p><input id="source-title" placeholder="Title, if known"><input id="source-creator" placeholder="Creator, if known"><input id="source-date" placeholder="Publication date, if known"><input id="capture-date" placeholder="Capture date, if known"></p><textarea id="transcript" placeholder="Paste transcript; keep timestamps and wording as captured." rows="7" style="width:min(700px,85vw)"></textarea><p><textarea id="coverage" placeholder="Transcript source, coverage and verification notes" rows="3" style="width:min(700px,85vw)"></textarea><textarea id="source-references" placeholder="Related source/reference paths or URLs; one per line" rows="2" style="width:min(700px,85vw)"></textarea><textarea id="lesson" placeholder="Extracted lesson, grounded in the source" rows="3" style="width:min(700px,85vw)"></textarea><textarea id="why" placeholder="Why save this?" rows="2" style="width:min(700px,85vw)"></textarea><textarea id="when" placeholder="When to use; one per line" rows="3" style="width:min(700px,85vw)"></textarea><textarea id="assumptions" placeholder="Assumptions and verification caveats; one per line" rows="3" style="width:min(700px,85vw)"></textarea><textarea id="examples" placeholder="Examples / extracted topics; one per line" rows="3" style="width:min(700px,85vw)"></textarea></p><p><input id="evidence-images" placeholder="Evidence image paths under H:\\NEXEN\\intake, separated by ;" style="width:min(700px,85vw)"></p></details><button id="build" class="primary">Build reel asset</button><button id="refresh">Refresh</button><span id="status" class="muted"></span></div>
<div id="cards" class="grid"></div>
<div id="modal"><div class="box"><button id="close" style="float:right">Close</button><div id="modal-body"></div></div></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Nexen-Action':'launch',...options.headers}});const x=await r.json();if(!r.ok)throw Error(typeof x.detail==='string'?x.detail:JSON.stringify(x.detail));return x}
function card(a){const evidence=[...(a.screenshots||[]).slice(0,3),...(a.examples||[]).slice(0,Math.max(0,3-(a.screenshots||[]).length))];return `<article class="card glass" tabindex="0"><div class="tag">${esc(a.status)} &middot; ${a.status==='tested'&&a.executable?'TESTED WORKFLOW':(a.status==='converted'?'DRAFT ONLY · REFERENCE EXECUTION':(a.executable?'PLACEHOLDER WORKFLOW':'REFERENCE ONLY'))}</div><b>${esc(a.title)}</b><p class="muted">${esc(a.one_line_purpose)}</p>
<div class="hover"><p><b>Why:</b> ${esc(a.why)}</p><p><b>When to use:</b> ${a.when_to_use.map(esc).join(', ')}</p><p><b>If opened/run:</b> ${esc(a.what_happens_if_run)}</p><p class="muted">Skill ${esc(a.skill_id)} &middot; Workflow ${esc(a.workflow_id)} &middot; ${esc(a.creator||'creator unknown')} &middot; ${esc(a.source_date||'date unknown')}</p><img class="mini-diagram" src="/api/reel-assets/${esc(a.id)}/diagram.svg" alt="Source to skill to n8n workflow diagram"><pre>${esc(a.diagram)}</pre>${evidence.length?`<div class="examples">${evidence.map(s=>typeof s==='string'?`<span>${esc(s)}</span>`:`<a href="${esc(s.url)}" target="_blank" rel="noopener"><img loading="lazy" alt="${esc(s.alt||'Source example')}" src="${esc(s.url)}"></a>`).join('')}</div>`:'<p class="muted">No source screenshots or examples attached.</p>'}
<div class="actions">${a.actions.open_skill?`<a href="${a.actions.open_skill}" target="_blank" rel="noopener">Open Skill</a>`:''}${a.actions.open_workflow?`<a href="${a.actions.open_workflow}" target="_blank" rel="noopener">Open Workflow JSON</a>`:''}<button data-expand="${a.id}">Expand Preview</button><a href="${esc(a.source_url)}" target="_blank" rel="noopener">View Source</a></div></div></article>`}
async function load(){$('status').textContent='Loading...';try{const d=await api('/api/reel-assets');$('cards').innerHTML=d.assets.length?d.assets.map(card).join(''):'<p class="muted">No reel assets yet. Add a transcript or use an indexed YouTube source.</p>';$('status').textContent=d.count+' asset(s) loaded.'}catch(e){$('status').textContent=e.message}}
document.addEventListener('click',async e=>{const btn=e.target.closest('[data-expand]');if(!btn)return;try{const d=await api('/api/reel-assets/'+btn.dataset.expand);$('modal-body').innerHTML=`<h2>${esc(d.title)}</h2><p class="muted">${esc(d.lifecycle)} &middot; asset ${esc(d.id)} &middot; linked skill/workflow ${esc(d.id)} &middot; source ${esc(d.source_id)}</p><h3>Source reference</h3><pre>${esc(d.source_reference)}</pre><h3>Diagram</h3>${d.diagram_svg?`<img style="width:100%;max-height:160px;object-fit:contain;background:#04101c" src="/api/reel-assets/${esc(d.id)}/diagram.svg" alt="Source to skill to workflow">`:''}<pre>${esc(d.diagram_mermaid)}</pre><h3>Skill</h3><pre>${esc(d.skill_markdown)}</pre><h3>Workflow inputs / outputs and execution status</h3><pre>${esc(JSON.stringify(d.workflow,null,2))}</pre><h3>Source transcript</h3><pre>${esc(d.source_transcript)}</pre><h3>Verification notes</h3><pre>${esc(d.verification_notes)}</pre><h3>Metadata and evaluation evidence</h3><pre>${esc(JSON.stringify(d.metadata,null,2))}</pre>`;$('modal').style.display='block'}catch(err){alert(err.message)}});
$('close').onclick=()=>$('modal').style.display='none';$('refresh').onclick=load;
$('build').onclick=async()=>{const id=$('source-id').value.trim();const url=$('source-url').value.trim();const lines=s=>$(s).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);let body;if(id)body={source_id:id};else body={source_url:url,title:$('#source-title').value.trim(),creator:$('#source-creator').value.trim()||null,source_date:$('#source-date').value.trim()||null,capture_date:$('#capture-date').value.trim()||null,transcript:$('#transcript').value,coverage:$('#coverage').value||undefined,source_references:lines('#source-references'),lesson:$('#lesson').value,why:$('#why').value,when_to_use:lines('#when'),assumptions:lines('#assumptions'),examples:lines('#examples'),evidence_images:$('#evidence-images').value.split(';').map(x=>x.trim()).filter(Boolean)};$('build').disabled=true;$('status').textContent='Building...';try{await api('/api/reel-assets',{method:'POST',body:JSON.stringify(body)});await load();$('status').textContent='Built.'}catch(e){$('status').textContent=e.message}finally{$('build').disabled=false}};
load();
</script></html>'''

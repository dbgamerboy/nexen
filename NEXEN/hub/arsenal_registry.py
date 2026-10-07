"""Arsenal registry: every downloaded repo, indexed skill, installed skill and Arsenal card
in one searchable index for MARVIN (V3 contract).

Sources (all read only):
  H:/NEXEN/arsenal/DOWNLOAD-RECEIPT.json        downloaded repos (repo, category, path, head, size_mb)
  H:/NEXEN/arsenal/repos/<owner>__<name>/       README first paragraph, _nexen/DIGEST.txt, _nexen/DIAGRAM.md
  H:/NEXEN/arsenal/SKILLS-INDEX.json            indexed skills (name, repo, description, path)
  H:/NEXEN/arsenal/SKILLS-INSTALL-RECEIPT.json  which indexed skills were copied into Claude's skills folder
  %USERPROFILE%/.claude/skills/*/      installed skills (SKILL.md frontmatter; never written)
  F:/NEXEN_MEMORY/20-Arsenal/cards/*.md         Arsenal cards (money lane, verdict, money score)
  H:/NEXEN/arsenal/MONEY-RUNNABLE.json          optional install/run/n8n notes per repo

Cache: H:/NEXEN/arsenal/REGISTRY.json. load() compares a cheap fingerprint of every source
(mtime/size of receipts, folder listings, card mtimes, digest/diagram presence) with the cache
and rebuilds when anything changed, so new repos, skills, cards and digests show up without code
changes. Digest/diagram-only changes are patched in place without a full rebuild.
Stdlib only. Nothing here raises into a route: missing sources degrade to zero counts plus a note.
"""
import hashlib
import heapq
import html
import json
import math
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 3
KINDS = ('repo', 'skill', 'card')
RESULT_KEYS = ('kind', 'name', 'repo', 'description', 'path', 'money_lane', 'score')
CHECK_SECONDS = 10.0          # in-process: re-check source fingerprints at most this often
README_BYTES = 256 * 1024
CARD_BYTES = 64 * 1024
SKILL_MD_BYTES = 24 * 1024
DESC_CHARS = 300

ARSENAL = Path(os.environ.get('NEXEN_ARSENAL_ROOT', 'H:/NEXEN/arsenal'))


def default_paths():
    return {
        'download_receipt': ARSENAL / 'DOWNLOAD-RECEIPT.json',
        'repos_dir': ARSENAL / 'repos',
        'skills_index': ARSENAL / 'SKILLS-INDEX.json',
        'skills_install': ARSENAL / 'SKILLS-INSTALL-RECEIPT.json',
        'skills_dir': Path(os.environ.get('NEXEN_CLAUDE_SKILLS', '%USERPROFILE%/.claude/skills')),
        'cards_dir': Path(os.environ.get('NEXEN_ARSENAL_CARDS', 'F:/NEXEN_MEMORY/20-Arsenal/cards')),
        'money_runnable': ARSENAL / 'MONEY-RUNNABLE.json',
        'cache': ARSENAL / 'REGISTRY.json',
    }


PATHS = default_paths()

# ----------------------------------------------------------------------------- money lanes
# Lane ids match F:/NEXEN_MEMORY/10-Segments/01-money-n8n/MONEY-LANES.json, plus three buckets
# for things that are not a revenue lane on their own.
LANE_RANK = {'service-100': 1, 'clip-service': 2, 'listing-media': 3, 'lumipaw-affiliate': 4,
             'digital-offer': 5, 'viral-niche': 6, 'music-money': 7,
             'coding-infra': 8, 'trading-research': 9, 'none': 10}
LANE_WORDS = {
    'service-100': ('n8n', 'automation', 'automate', 'workflow', 'lead', 'leads', 'lead-gen', 'scraper', 'crm',
                    'outreach', 'agency', 'client', 'clients', 'local business', 'small business', 'audit',
                    'website', 'websites', 'service offer', 'service offers', 'freelance', 'upwork', 'invoice'),
    'clip-service': ('clip', 'clips', 'clipping', 'clipper', 'highlight', 'highlights', 'repurpose', 'repurposing',
                     'long video', 'long-form', 'podcast', 'subtitle', 'subtitles', 'caption', 'captions',
                     '9:16', 'vertical', 'autoclipper', 'video editing', 'edit video', 'cut'),
    'listing-media': ('slideshow', 'real estate', 'realtor', 'listing', 'listings', 'property', 'house tour'),
    'lumipaw-affiliate': ('affiliate', 'tiktok shop', 'product video', 'ugc', 'e-commerce', 'ecommerce', 'commerce',
                          'storefront', 'lumipaw', 'curviana', 'dropship', 'top products', 'shop'),
    'digital-offer': ('course', 'template', 'templates', 'ebook', 'digital product', 'kdp', 'coloring',
                      'gumroad', 'prompt pack', 'midi pack', 'loop pack', 'sample pack', 'pre-order', 'merch'),
    'viral-niche': ('faceless', 'viral', 'tiktok', 'youtube', 'shorts', 'reels', 'trend', 'trending', 'hook',
                    'hooks', 'niche', 'channel', 'channels', 'thumbnail', 'thumbnails', 'voiceover', 'tts',
                    'text-to-speech', 'b-roll', 'cover art'),
    'music-money': ('music', 'song', 'songs', 'beat', 'beats', 'stem', 'stems', 'vocal', 'vocals', 'mix', 'mixing',
                    'mastering', 'master', 'midi', 'dj', 'singing', 'pitch', 'instrumental', 'wdr', 'catalog',
                    'acapella', 'loudness'),
    'trading-research': ('trading', 'trade', 'betting', 'odds', 'stock', 'stocks', 'crypto', 'forecast',
                         'hedge', 'sportsbook', 'portfolio', 'backtest', 'finance', 'financial'),
    'coding-infra': ('agent', 'agents', 'coding', 'code', 'codebase', 'mcp', 'llm', 'claude', 'codex', 'memory',
                     'rag', 'browser', 'cli', 'harness', 'skills', 'developer', '24/7', 'infrastructure', 'infra'),
}
CATEGORY_LANE = {'money': 'service-100', 'video': 'viral-niche', 'music': 'music-money', 'visual': 'viral-niche',
                 'research': 'coding-infra', 'trading': 'trading-research', 'agents': 'coding-infra',
                 'system': 'coding-infra'}
_LANE_RX = {lane: re.compile(r'(?<![a-z0-9])(?:' + '|'.join(re.escape(w) for w in words) + r')(?![a-z0-9])')
            for lane, words in LANE_WORDS.items()}


def classify_lane(text, category='', card_lane=''):
    """Best money lane id for free text. Card lane text counts double, the category is a prior."""
    scores = Counter()
    for weight, chunk in ((2.0, card_lane), (1.0, text)):
        low = (chunk or '').lower()
        if not low:
            continue
        for lane, rx in _LANE_RX.items():
            hits = len(rx.findall(low))
            if hits:
                scores[lane] += weight * min(hits, 4)
    prior = CATEGORY_LANE.get((category or '').lower())
    if prior:
        scores[prior] += 1.5
    if not scores:
        return 'none'
    best = max(scores.values())
    tied = [lane for lane, value in scores.items() if value == best]
    if prior in tied:
        return prior
    return min(tied, key=lambda lane: LANE_RANK.get(lane, 99))


# ----------------------------------------------------------------------------- top money tonight
# Hand-picked after reading each README (2026-09-26): runnable on PC1 at $0 (CPU or RTX 2070 8GB,
# local Ollama, ffmpeg) and tied to a lane in MONEY-LANES.json. Run commands are quoted from the
# README. If a repo disappears it is skipped and the list is filled from card scores.
TOP_MONEY = (
    ('guillaumegay13/youtube-to-viral-clips',
     'Clip-service sample pack: long rights-cleared video -> scored 9:16 captioned clips with local Whisper + Ollama, no API key.',
     'python main.py --file "episode.mp4" --layout split-stack --subtitle-style "Viral Highlight"'),
    ('VladPolus/ViriaRevive',
     'Second clip engine: best-moment detection, face-tracked 9:16 crop, styled subtitles, Ollama titles (never use --upload).',
     'python main.py "URL" --clips 5 --duration 30 --style bold'),
    ('calesthio/PhantomReach',
     'Free public-footprint audit of a local business = pitch-ready lead magnet for the $100 automation offer; runs without AI keys.',
     'npm run local'),
    ('FFmpeg/FFmpeg',
     'Every video lane: cut, 9:16 reframe, caption burn-in, listing photo slideshows. Binary already at H:/NEXEN/toolroot/ffmpeg.',
     'H:/NEXEN/toolroot/ffmpeg/bin/ffmpeg.exe -i in.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" -c:a copy out_9x16.mp4'),
    ('openai/whisper',
     'Transcripts + captions for clips and podcasts; turbo model fits the 8GB RTX 2070 (faster-whisper already in H:/NEXEN/transcription-runtime).',
     'whisper audio.mp3 --model turbo'),
    ('harry0703/MoneyPrinterTurbo',
     'Faceless-shorts render engine: topic -> script (local Ollama) -> footage -> Edge TTS voice -> subtitled vertical video.',
     'uv run python cli.py --video-subject "How AI is changing everyday life"'),
    ('facebookresearch/demucs',
     'Stems and acapellas for the $75 mix offer and the WDR catalog (task 94); runs on the RTX 2070.',
     'demucs "my music/my favorite track.mp3"'),
    ('sergree/matchering',
     'Reference-matched mastering for the $50 master offer, CPU only, no account.',
     'python -c "import matchering as mg; mg.process(target=\'my_song.wav\', reference=\'ref.wav\', results=[mg.pcm16(\'my_song_master.wav\')])"'),
    ('heygen-com/hyperframes',
     'HTML -> MP4 templates (listing slideshows, product roundups, lyric cards); Apache-2.0, no per-render fees.',
     'npx hyperframes init my-video && npx hyperframes render'),
    ('travisvn/openai-edge-tts',
     'Free OpenAI-compatible voiceover endpoint (Edge TTS, no key) for faceless, product and slideshow videos.',
     'python app/server.py'),
)

# ----------------------------------------------------------------------------- text helpers
_STOP = frozenset('''a an and are as at be by for from has have how i in into is it its of on or that the this to
use used using via was what when where which who will with you your can do does me my we our not no all any more
most make also just than then there these they them so if but out up only one it's'''.split())
_WORD = re.compile(r'[a-z0-9]+')
_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')


def _norm_word(w):
    if len(w) > 4 and w.endswith('ies'):
        w = w[:-3] + 'y'
    elif len(w) > 5 and w.endswith('ing'):
        w = w[:-3]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in 'aeiouls':
            w = w[:-1]
    elif len(w) > 4 and w.endswith('ed') and not w.endswith('eed'):
        w = w[:-2]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in 'aeiouls':
            w = w[:-1]
    elif len(w) > 3 and w.endswith('s') and not w.endswith(('ss', 'us', 'is')):
        w = w[:-1]
    if len(w) > 4 and w.endswith('e'):
        w = w[:-1]
    return w


def tokens(text):
    """Lowercase, split camelCase and punctuation, drop stopwords, light stemming."""
    out = []
    for w in _WORD.findall(_CAMEL.sub(' ', str(text or '')).lower()):
        if w in _STOP or (len(w) < 2 and not w.isdigit()):
            continue
        out.append(_norm_word(w))
    return out


_SYNONYMS = {
    'tiktok': ('short', 'reel', 'vertical'), 'short': ('tiktok', 'reel', 'clip'), 'reel': ('short', 'tiktok'),
    'clip': ('highlight', 'short'), 'video': ('clip', 'footage'), 'song': ('music', 'track'),
    'music': ('song', 'beat', 'audio'), 'beat': ('music', 'instrumental'), 'voice': ('tts', 'speech', 'narration'),
    'tts': ('voice', 'speech'), 'caption': ('subtitle',), 'subtitle': ('caption',), 'lead': ('prospect', 'scraper'),
    'scrape': ('scraper', 'crawl'), 'money': ('revenue', 'monetize', 'income'), 'thumbnail': ('cover', 'image'),
    'master': ('mastering', 'loudness'), 'stem': ('separation', 'acapella'), 'transcribe': ('transcript', 'whisper'),
}
_SYN = {}
for _k, _vs in _SYNONYMS.items():
    _key = (tokens(_k) or [_k])[0]
    _SYN[_key] = tuple(t for v in _vs for t in tokens(v))

_HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
_FENCE = re.compile(r'(```|~~~).*?(\1|\Z)', re.S)
_IMG = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_REF_LINK = re.compile(r'\[([^\]]*)\]\[[^\]]*\]')
_TAG = re.compile(r'<[^>]+>')
_EMPH = re.compile(r'(\*\*|__|`)')
_SKIP_PARA = ('sponsor', 'thanks to', 'star history', 'trendshift', 'buy me a coffee', 'table of contents',
              'this readme', 'dieses readme', 'join our discord', 'click here', 'affiliate link')


def _clip(text, limit):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(',;:-')
    return cut + '...'


def _plain(markdown):
    text = _IMG.sub('', markdown)
    text = _LINK.sub(r'\1', text)
    text = _REF_LINK.sub(r'\1', text)
    text = _TAG.sub(' ', text)
    text = _EMPH.sub('', text)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip(' -:|*')


def first_paragraph(text, limit=360):
    """First real prose paragraph of a README: skips badges, headings, tables, code, sponsors, non-English."""
    text = _FENCE.sub('\n\n', _HTML_COMMENT.sub('', str(text or '')))
    for block in re.split(r'\n\s*\n', text):
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        head = lines[0]
        if head.startswith(('#', '|', '---', '===', '- ', '* ', '+ ')) or re.match(r'^\d+[.)] ', head):
            continue
        plain = _plain(' '.join(line.lstrip('>').strip() for line in lines))
        letters = sum(c.isalpha() for c in plain)
        if letters < 40:
            continue
        if sum(c.isascii() and c.isalpha() for c in plain) / letters < 0.75:
            continue
        low = plain.lower()
        if any(word in low for word in _SKIP_PARA) or plain.count(' | ') > 2:
            continue
        return _clip(plain, limit)
    return ''


def readme_excerpt(text, limit=1200):
    """Cleaned prose + headings from the top of a README, for search recall only."""
    text = _FENCE.sub(' ', _HTML_COMMENT.sub('', str(text or '')[:20000]))
    return _clip(_plain(text.replace('#', ' ')), limit)


_RUN_BASE = {'python': 3, 'python3': 3, 'py': 2, 'uv': 3, 'uvx': 3, 'npm': 2, 'npx': 2, 'pnpm': 2, 'yarn': 2,
             'bun': 2, 'node': 2, 'streamlit': 3, 'docker': 1, 'docker-compose': 1, 'make': 1, 'go': 1,
             'cargo': 1, 'bash': 1, 'sh': 1, 'deno': 2}
_RUN_BAD = re.compile(r'(?<![\w-])(install|clone|build|test|tests|lint|update|upgrade|venv|activate|pull|cd|export|'
                      r'set|mkdir|git|setup|uninstall|pip|sync|conda|brew|apt|apt-get|curl|wget|choco|winget|'
                      r'nvidia-smi|exec|ps|logs|format|typecheck|tsc|drizzle-kit|pack:dir|dist|login|--help|'
                      r'--version|-h)(?![\w-])')
_RUN_GOOD = re.compile(r'(?<![\w-])(run|start|serve|dev|main|app|cli|local|up|generate|render|process)(?![\w-])')


def extract_run(readme_text, repo_name=''):
    """Most likely 'run it' command inside the README's code blocks ('' when none)."""
    names = {n for n in {repo_name.lower(), repo_name.lower().replace('_', '-')} if n}
    best, best_score = '', 0
    for block in re.findall(r'```[^\n]*\n(.*?)```', str(readme_text or ''), re.S):
        for raw in block.splitlines():
            line = re.sub(r'^\s*(\$|>|PS>|C:\\>)\s*', '', raw).strip()
            line = re.sub(r'\s+#\s.*$', '', line).strip()
            if not line or len(line) > 200 or line.startswith(('#', '//')) or line.endswith('\\'):
                continue
            first = line.split()[0].lower()
            base = 5 if first in names else _RUN_BASE.get(first, 2 if first.startswith('./') else 0)
            if not base or _RUN_BAD.search(line.lower()):
                continue
            score = base + (1 if len(line.split()) >= 3 else 0) + (1 if _RUN_GOOD.search(line.lower()) else 0)
            if score > best_score:
                best, best_score = line, score
    return best


def frontmatter(text):
    """Tiny YAML-frontmatter reader: scalars, quoted strings, [lists] and |/> block scalars."""
    match = re.match(r'^\ufeff?---\s*\r?\n(.*?)\r?\n---\s*(\r?\n|$)', str(text or ''), re.S)
    if not match:
        return {}, str(text or '')
    data, lines, i = {}, match.group(1).splitlines(), 0
    while i < len(lines):
        line = lines[i]
        i += 1
        m = re.match(r'^([A-Za-z0-9_.-]+)\s*:\s*(.*)$', line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        if value in ('|', '>', '|-', '>-', '|+', '>+'):
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (' ', '\t')):
                block.append(lines[i].strip())
                i += 1
            value = ' '.join(x for x in block if x)
        elif value.startswith('[') and value.endswith(']'):
            value = [x.strip().strip('"\'') for x in value[1:-1].split(',') if x.strip()]
        else:
            value = value.strip('"\'')
        data[key] = value
    return data, text[match.end():]


def _clean_desc(value):
    value = str(value or '').replace('\\"', '"').replace('\\n', ' ').replace('\\\\', '\\')
    value = value.strip().strip('"\'')
    return '' if value in ('|', '>', '|-', '>-', '|+', '>+') else _clip(value, DESC_CHARS)


def _read_text(path, limit):
    try:
        with open(path, 'rb') as stream:
            return stream.read(limit).decode('utf-8', 'replace').lstrip('\ufeff')
    except OSError:
        return ''


def _read_json(path):
    try:
        with open(path, 'rb') as stream:
            return json.loads(stream.read().decode('utf-8-sig'))
    except (OSError, ValueError):
        return None


def _norm_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


def _iso(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).astimezone().isoformat(timespec='seconds')


# ----------------------------------------------------------------------------- fingerprint
def _paths(paths=None):
    merged = dict(PATHS)
    if paths:
        merged.update({k: Path(v) for k, v in paths.items()})
    return merged


def _stat(path):
    try:
        st = os.stat(path)
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def _subdirs(path):
    try:
        with os.scandir(path) as it:
            return sorted(e.name for e in it if e.is_dir() and not e.name.startswith(('.', '_')))
    except OSError:
        return []


def _nexen_files(repo_dir):
    try:
        with os.scandir(os.path.join(repo_dir, '_nexen')) as it:
            return {e.name for e in it if e.is_file()}
    except OSError:
        return set()


def _light(paths):
    """Digest/diagram presence under repos_dir (the digest job keeps adding these)."""
    root = str(paths['repos_dir'])
    digests, diagrams = [], []
    for name in _subdirs(root):
        files = _nexen_files(os.path.join(root, name))
        if 'DIGEST.txt' in files:
            digests.append(name)
        if 'DIAGRAM.md' in files:
            diagrams.append(name)
    digest = hashlib.sha1(('|'.join(digests) + '#' + '|'.join(diagrams)).encode('utf-8')).hexdigest()
    return {'hash': digest, 'digests': digests, 'diagrams': diagrams}


def fingerprint(paths=None):
    """(heavy, light): heavy covers everything that needs a rebuild, light only digest/diagram flags."""
    p = _paths(paths)
    h = hashlib.sha1()
    for key in ('download_receipt', 'skills_index', 'skills_install', 'money_runnable'):
        h.update(('%s=%s;' % (key, _stat(p[key]))).encode('utf-8'))
    h.update(('repos=' + '|'.join(_subdirs(p['repos_dir']))).encode('utf-8'))
    for key, want_dir in (('skills_dir', True), ('cards_dir', False)):
        try:
            with os.scandir(p[key]) as it:
                rows = []
                for e in it:
                    if want_dir != e.is_dir() or (not want_dir and not e.name.lower().endswith('.md')):
                        continue
                    st = e.stat()
                    rows.append('%s:%s:%s' % (e.name, st.st_mtime_ns, 0 if want_dir else st.st_size))
        except OSError:
            rows = ['missing']
        h.update(('%s=%s;' % (key, '|'.join(sorted(rows)))).encode('utf-8'))
    h.update(('schema=%s' % SCHEMA).encode('utf-8'))
    return h.hexdigest(), _light(p)


# ----------------------------------------------------------------------------- build
def _readme(repo_dir):
    try:
        with os.scandir(repo_dir) as it:
            names = [e.name for e in it if e.is_file() and e.name.lower().startswith('readme')]
    except OSError:
        return '', ''
    order = ('readme.md', 'readme.en.md', 'readme-en.md', 'readme_en.md', 'readme.markdown', 'readme.rst',
             'readme.txt', 'readme')
    lower = {n.lower(): n for n in names}
    ordered = [lower[n] for n in order if n in lower]
    ordered += sorted(n for n in names if n not in ordered)
    first_text = ''
    for name in ordered[:4]:
        text = _read_text(os.path.join(repo_dir, name), README_BYTES)
        if not first_text:
            first_text = text
        para = first_paragraph(text)
        if para:
            return text, para
    return first_text, ''


def _repo_rows(p, notes):
    data = _read_json(p['download_receipt'])
    rows, seen = [], set()
    if isinstance(data, dict) and isinstance(data.get('repos'), list):
        for r in data['repos']:
            if not isinstance(r, dict) or not str(r.get('repo') or '').strip():
                continue
            repo_id = str(r['repo']).strip().strip('/')
            slug = repo_id.replace('/', '__')
            path = Path(str(r.get('path') or ''))
            if not str(r.get('path') or '') or not path.is_dir():
                path = p['repos_dir'] / slug
            if not path.is_dir() or slug.lower() in seen:
                continue
            seen.add(slug.lower())
            rows.append({'repo': repo_id, 'slug': slug, 'path': path, 'category': str(r.get('category') or ''),
                         'head': str(r.get('head') or '')[:12], 'size_mb': r.get('size_mb'),
                         'flag': str(r.get('note') or '')})
    else:
        notes.append('DOWNLOAD-RECEIPT.json missing or unreadable; repos listed from the repos folder only.')
    for slug in _subdirs(p['repos_dir']):
        if slug.lower() in seen:
            continue
        seen.add(slug.lower())
        repo_id = slug.replace('__', '/', 1) if '__' in slug else slug
        rows.append({'repo': repo_id, 'slug': slug, 'path': p['repos_dir'] / slug, 'category': 'unlisted',
                     'head': '', 'size_mb': None, 'flag': 'not in DOWNLOAD-RECEIPT (downloaded later?)'})
    return rows


def _parse_card(path):
    text = _read_text(path, CARD_BYTES)
    fm, body = frontmatter(text)
    sections, current = {}, None
    for line in body.splitlines():
        if line.startswith('## '):
            current = re.sub(r'[^a-z0-9 ]', '', line[3:].lower()).strip()
            sections[current] = []
        elif current is not None and line.strip():
            sections[current].append(line.strip())

    def section(*keys):
        for name, lines in sections.items():
            if any(k in name for k in keys):
                return _plain(' '.join(lines))
        return ''

    try:
        score = float(fm.get('money_score'))
    except (TypeError, ValueError):
        score = None
    aliases = fm.get('aliases') if isinstance(fm.get('aliases'), list) else []
    name = fm.get('name') if isinstance(fm.get('name'), str) and fm.get('name') else Path(path).stem
    first = next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith('#')), '')
    return {'name': name, 'url': str(fm.get('url') or ''), 'aliases': aliases,
            'category': str(fm.get('category') or ''), 'lane_text': str(fm.get('money_lane') or ''),
            'money_score': score, 'verdict': str(fm.get('verdict') or ''),
            'time_to_first_dollar': str(fm.get('time_to_first_dollar') or ''),
            'flags': fm.get('flags') if isinstance(fm.get('flags'), str) else ', '.join(fm.get('flags') or []),
            'what': section('what it is') or _plain(first), 'does': section('what it does'),
            'play': section('undeniable play'), 'workflow': section('workflow')}


def _github_id(url):
    m = re.search(r'github\.com/([\w.-]+)/([\w.-]+)', str(url or ''), re.I)
    if not m:
        return ''
    name = m.group(2)
    return '%s/%s' % (m.group(1), name[:-4] if name.lower().endswith('.git') else name)


def _match_card(card, stem, by_id, by_slug, by_name):
    gid = _github_id(card['url'])
    if gid and gid.lower() in by_id:
        return by_id[gid.lower()]
    for alias in card['aliases']:
        if '/' in alias and alias.strip().lower() in by_id:
            return by_id[alias.strip().lower()]
    if _norm_key(stem) in by_slug:
        return by_slug[_norm_key(stem)]
    names = by_name.get(_norm_key(card['name'])) or []
    return names[0] if len(names) == 1 else ''


def _terms(*parts, name=''):
    toks = []
    for _ in range(3):
        toks += tokens(name)
    joined = _norm_key(name)
    if joined and len(joined) > 2:
        toks.append(joined)
    for part in parts:
        toks += tokens(part)
    return ' '.join(toks)


def _skill_description(skill_dir):
    fm, _ = frontmatter(_read_text(os.path.join(str(skill_dir), 'SKILL.md'), SKILL_MD_BYTES))
    return _clean_desc(fm.get('description') if isinstance(fm.get('description'), str) else '')


def build(paths=None):
    """Read every source and return a fresh registry dict (does not write the cache)."""
    started = time.perf_counter()
    p = _paths(paths)
    heavy, light = fingerprint(p)
    notes = []

    # ---- repos
    repos = []
    for row in _repo_rows(p, notes):
        text, para = _readme(str(row['path']))
        files = _nexen_files(str(row['path']))
        short = row['repo'].split('/')[-1]
        repos.append({'kind': 'repo', 'name': short, 'repo': row['repo'], 'description': para,
                      'path': str(row['path']), 'money_lane': 'none', 'category': row['category'],
                      'head': row['head'], 'size_mb': row['size_mb'], 'flag': row['flag'],
                      'digest': 'DIGEST.txt' in files, 'diagram': 'DIAGRAM.md' in files,
                      'run': extract_run(text, short), '_readme': readme_excerpt(text), '_slug': row['slug']})
    by_id = {r['repo'].lower(): r['repo'] for r in repos}
    by_slug = {_norm_key(r['_slug']): r['repo'] for r in repos}
    by_name = {}
    for r in repos:
        by_name.setdefault(_norm_key(r['name']), []).append(r['repo'])
    repo_doc = {r['repo']: r for r in repos}

    # ---- cards
    cards = []
    try:
        card_files = sorted(e.path for e in os.scandir(p['cards_dir']) if e.is_file() and e.name.lower().endswith('.md'))
    except OSError:
        card_files = []
        notes.append('Arsenal cards folder missing: %s' % p['cards_dir'])
    for cpath in card_files:
        card = _parse_card(cpath)
        matched = _match_card(card, Path(cpath).stem, by_id, by_slug, by_name)
        lane = classify_lane(' '.join((card['name'], card['what'], card['does'])), card_lane=card['lane_text'])
        cards.append({'kind': 'card', 'name': card['name'], 'repo': matched or _github_id(card['url']),
                      'description': _clip(card['what'] or card['does'], DESC_CHARS), 'path': cpath,
                      'money_lane': lane, 'url': card['url'], 'verdict': card['verdict'],
                      'money_score': card['money_score'], 'time_to_first_dollar': card['time_to_first_dollar'],
                      'lane_text': card['lane_text'], 'downloaded': bool(matched), 'play': _clip(card['play'], 240),
                      'flags': card['flags'],
                      'terms': _terms(card['category'], card['lane_text'], card['what'], card['does'], card['play'],
                                      matched, name=card['name'])})
        if matched:
            doc = repo_doc[matched]
            best = doc.get('money_score')
            if best is None or (card['money_score'] or 0) > best:
                doc.update({'card': cpath, 'verdict': card['verdict'], 'money_score': card['money_score'],
                            'lane_text': card['lane_text'], 'play': _clip(card['play'], 240),
                            'time_to_first_dollar': card['time_to_first_dollar'], '_card_what': card['what']})

    # ---- optional MONEY-RUNNABLE notes
    runnable = _read_json(p['money_runnable'])
    for entry in (runnable or {}).get('repos', []) if isinstance(runnable, dict) else []:
        if isinstance(entry, dict) and str(entry.get('repo', '')).lower() in by_id:
            keep = {k: entry.get(k) for k in ('rank', 'lane', 'install', 'run', 'inputs', 'n8n', 'status') if k in entry}
            repo_doc[by_id[str(entry['repo']).lower()]]['runnable'] = keep

    for doc in repos:
        doc['money_lane'] = classify_lane(' '.join((doc['name'], doc['description'], doc.get('_card_what', ''))),
                                          doc['category'], doc.get('lane_text', ''))
        if not doc['description']:
            doc['description'] = _clip(doc.get('_card_what') or doc['repo'], DESC_CHARS)
        doc['terms'] = _terms(doc['repo'].replace('/', ' '), doc['category'], doc['description'],
                              doc.get('lane_text', ''), doc.get('_card_what', ''), doc.get('play', ''),
                              doc['money_lane'].replace('-', ' '), doc['_readme'], name=doc['name'])
        for key in ('_readme', '_card_what'):
            doc.pop(key, None)

    # ---- skills
    index = _read_json(p['skills_index'])
    if not isinstance(index, list):
        notes.append('SKILLS-INDEX.json missing or unreadable.')
        index = []
    install = _read_json(p['skills_install'])
    installed_pairs = set()
    if isinstance(install, dict):
        for row in install.get('installed') or []:
            if isinstance(row, dict):
                installed_pairs.add((str(row.get('name', '')), str(row.get('repo', ''))))
    installed_dirs = {}
    try:
        for e in os.scandir(p['skills_dir']):
            if e.is_dir() and os.path.isfile(os.path.join(e.path, 'SKILL.md')):
                installed_dirs[e.name] = e.path
    except OSError:
        notes.append('Installed skills folder missing: %s' % p['skills_dir'])
    slug_to_id = {r['_slug'].lower(): r['repo'] for r in repos}
    category_of = {r['repo']: r['category'] for r in repos}
    skills, seen, claimed = [], set(), set()
    for row in index:
        if not isinstance(row, dict) or not str(row.get('name') or '').strip():
            continue
        name, slug = str(row['name']).strip(), str(row.get('repo') or '').strip()
        src = str(row.get('path') or '')
        key = (name, slug, src)
        if key in seen:
            continue
        seen.add(key)
        repo_id = slug_to_id.get(slug.lower()) or (slug.replace('__', '/', 1) if '__' in slug else slug)
        desc = _clean_desc(row.get('description'))
        if len(desc) < 8 and src:
            desc = _skill_description(src) or desc
        is_installed = (name, slug) in installed_pairs and name in installed_dirs
        if is_installed:
            claimed.add(name)
        lane = classify_lane(name.replace('-', ' ') + ' ' + desc, category_of.get(repo_id, ''))
        skills.append({'kind': 'skill', 'name': name, 'repo': repo_id, 'description': desc,
                       'path': installed_dirs[name] if is_installed else src, 'money_lane': lane,
                       'installed': is_installed, 'source_path': src,
                       'terms': _terms(repo_id.split('/')[-1], desc, name=name)})
    for name, spath in sorted(installed_dirs.items()):
        if name in claimed:
            continue
        desc = _skill_description(spath)
        skills.append({'kind': 'skill', 'name': name, 'repo': 'installed', 'description': desc, 'path': spath,
                       'money_lane': classify_lane(name.replace('-', ' ') + ' ' + desc), 'installed': True,
                       'source_path': spath, 'terms': _terms(desc, name=name)})
    for doc in repos:
        doc.pop('_slug', None)

    docs = repos + skills + cards
    digests = sum(1 for r in repos if r['digest'])
    diagrams = sum(1 for r in repos if r['diagram'])
    lanes = Counter(d['money_lane'] for d in repos)
    registry = {
        'schema': SCHEMA, 'built_at': _iso(), 'build_ms': 0,
        'fingerprint': {'heavy': heavy, 'light': light['hash']},
        'counts': {'repos': len(repos), 'skills_installed': len(installed_dirs), 'skills_indexed': len(index),
                   'skill_docs': len(skills), 'cards': len(cards), 'cards_matched': sum(c['downloaded'] for c in cards),
                   'digests': digests, 'diagrams': diagrams, 'docs': len(docs)},
        'lanes': dict(sorted(lanes.items(), key=lambda kv: LANE_RANK.get(kv[0], 99))),
        'notes': notes,
        'top_money': _top_money(repos),
        'docs': docs,
    }
    registry['build_ms'] = int((time.perf_counter() - started) * 1000)
    return registry


def _top_money(repos, limit=10):
    by_id = {r['repo'].lower(): r for r in repos}
    top, used = [], set()
    for repo_id, why, run in TOP_MONEY:
        doc = by_id.get(repo_id.lower())
        if doc and len(top) < limit:
            top.append({'name': doc['name'], 'why': why, 'run': run or doc.get('run') or 'see README: ' + doc['path']})
            used.add(doc['repo'])
    skip = {'skip', 'later', 'overkill', 'unresolved', 'avoid', 'drop'}
    rest = [r for r in repos if r['repo'] not in used and LANE_RANK.get(r['money_lane'], 99) <= 7
            and str(r.get('verdict') or '').lower() not in skip]
    rest.sort(key=lambda r: (-(r.get('money_score') or 0), LANE_RANK.get(r['money_lane'], 99), r['name'].lower()))
    for doc in rest[:max(0, limit - len(top))]:
        why = doc.get('play') or doc['description']
        top.append({'name': doc['name'], 'why': _clip(why, 200),
                    'run': doc.get('run') or 'see README: ' + doc['path']})
    return top


# ----------------------------------------------------------------------------- cache + load
_MEM = {}
_MEM_LOCK = threading.Lock()
_BUILD_LOCK = threading.Lock()


def _write_cache(path, registry):
    path = Path(path)
    try:
        try:
            from storage_policy import require_output_path
            path = require_output_path(path)
        except ImportError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(registry, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, path)
        return True
    except (OSError, ValueError) as exc:
        registry.setdefault('notes', []).append('Registry cache not saved (%s).' % type(exc).__name__)
        return False


def _patch_light(registry, light, p):
    """Only digests/diagrams changed: flip flags on repo docs and re-save; no README/card re-read."""
    root = Path(p['repos_dir'])
    digests, diagrams = set(light['digests']), set(light['diagrams'])
    for doc in registry.get('docs', []):
        if doc.get('kind') == 'repo':
            repo_path = Path(doc.get('path', ''))
            if repo_path.parent == root:
                doc['digest'] = repo_path.name in digests
                doc['diagram'] = repo_path.name in diagrams
            else:
                files = _nexen_files(str(repo_path))
                doc['digest'], doc['diagram'] = 'DIGEST.txt' in files, 'DIAGRAM.md' in files
    repos = [d for d in registry.get('docs', []) if d.get('kind') == 'repo']
    registry['counts']['digests'] = sum(1 for d in repos if d.get('digest'))
    registry['counts']['diagrams'] = sum(1 for d in repos if d.get('diagram'))
    registry['fingerprint']['light'] = light['hash']
    registry['patched_at'] = _iso()
    _write_cache(p['cache'], registry)
    return registry


def _empty(note):
    return {'schema': SCHEMA, 'built_at': None, 'build_ms': 0, 'fingerprint': {'heavy': None, 'light': None},
            'counts': {'repos': 0, 'skills_installed': 0, 'skills_indexed': 0, 'skill_docs': 0, 'cards': 0,
                       'cards_matched': 0, 'digests': 0, 'diagrams': 0, 'docs': 0},
            'lanes': {}, 'notes': [note], 'top_money': [], 'docs': []}


def load(force=False, paths=None):
    """Registry dict. Cached in memory and at REGISTRY.json; rebuilt when any source changed."""
    p = _paths(paths)
    key = str(p['cache'])
    with _MEM_LOCK:
        slot = _MEM.get(key)
        if not force and slot and time.monotonic() - slot['checked'] < CHECK_SECONDS:
            return slot['reg']
    try:
        heavy, light = fingerprint(p)
        if not force:
            reg = slot['reg'] if slot else None
            if not reg or reg.get('fingerprint', {}).get('heavy') != heavy:
                cached = _read_json(p['cache'])
                if (isinstance(cached, dict) and cached.get('schema') == SCHEMA
                        and cached.get('fingerprint', {}).get('heavy') == heavy and isinstance(cached.get('docs'), list)):
                    reg, slot = cached, None
                else:
                    reg = None
            if reg is not None:
                if reg['fingerprint'].get('light') != light['hash']:
                    reg = _patch_light(reg, light, p)
                with _MEM_LOCK:
                    keep_index = slot['index'] if slot and slot['reg'] is reg else None
                    _MEM[key] = {'reg': reg, 'checked': time.monotonic(), 'index': keep_index}
                return reg
        # Build. If another thread is already building, serve the stale copy instead of waiting.
        if not _BUILD_LOCK.acquire(blocking=slot is None):
            return slot['reg']
        try:
            with _MEM_LOCK:
                fresh = _MEM.get(key)
            if not force and fresh and fresh['reg'].get('fingerprint', {}).get('heavy') == heavy:
                return fresh['reg']
            reg = build(p)
            _write_cache(p['cache'], reg)
            with _MEM_LOCK:
                _MEM[key] = {'reg': reg, 'checked': time.monotonic(), 'index': None}
            return reg
        finally:
            _BUILD_LOCK.release()
    except Exception as exc:  # noqa: BLE001 - never break a route over the registry
        if slot:
            return slot['reg']
        return _empty('Arsenal registry unavailable (%s).' % type(exc).__name__)


# ----------------------------------------------------------------------------- search
class _Index:
    K1, B = 1.4, 0.75

    def __init__(self, docs):
        self.post, self.dl = {}, []
        for i, doc in enumerate(docs):
            toks = str(doc.get('terms') or '').split()
            self.dl.append(len(toks) or 1)
            for term, n in Counter(toks).items():
                self.post.setdefault(term, []).append((i, n))
        self.n = len(docs)
        self.avg = (sum(self.dl) / self.n) if self.n else 1.0

    def idf(self, term):
        df = len(self.post.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, weighted):
        acc, hits = {}, {}
        for term, (weight, primary) in weighted.items():
            plist = self.post.get(term)
            if not plist:
                continue
            idf = self.idf(term) * weight
            for i, tf in plist:
                norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * self.dl[i] / self.avg))
                acc[i] = acc.get(i, 0.0) + idf * norm
                if primary:
                    hits.setdefault(i, set()).add(primary)
        return acc, hits


def _index_for(p, reg):
    key = str(p['cache'])
    with _MEM_LOCK:
        slot = _MEM.get(key)
        if slot and slot['reg'] is reg and slot.get('index') is not None:
            return slot['index']
    index = _Index(reg.get('docs', []))
    with _MEM_LOCK:
        slot = _MEM.get(key)
        if slot and slot['reg'] is reg:
            slot['index'] = index
    return index


def search(query, k=8, kinds=None, paths=None):
    """Top-k docs as [{kind, name, repo, description, path, money_lane, score}], best first."""
    try:
        k = max(1, min(int(k), 100))
    except (TypeError, ValueError):
        k = 8
    primary = []
    for t in tokens(str(query or '')[:500]):
        if t not in primary:
            primary.append(t)
    if not primary:
        return []
    if isinstance(kinds, str):
        kinds = [x.strip() for x in kinds.split(',')]
    allowed = {x for x in (kinds or KINDS) if x in KINDS} or set(KINDS)
    try:
        p = _paths(paths)
        reg = load(paths=paths)
        docs = reg.get('docs', [])
        if not docs:
            return []
        weighted = {t: (1.0, t) for t in primary}
        for t in primary:
            for syn in _SYN.get(t, ()):
                if syn not in weighted:
                    weighted[syn] = (0.35, t)
        acc, hits = _index_for(p, reg).scores(weighted)
        ranked = []
        for i, score in acc.items():
            doc = docs[i]
            if doc.get('kind') not in allowed:
                continue
            coverage = len(hits.get(i, ())) / len(primary)
            score *= 0.55 + 0.45 * coverage
            if doc.get('kind') == 'repo':
                score *= 1.05 + 0.02 * float(doc.get('money_score') or 0)
            elif doc.get('kind') == 'skill' and doc.get('installed'):
                score *= 1.1
            ranked.append((score, i))
        out, seen = [], set()
        for score, i in heapq.nlargest(k * 4 + 20, ranked):
            doc = docs[i]
            dedupe = (doc.get('kind'), str(doc.get('name', '')).lower())
            if dedupe in seen:
                continue
            seen.add(dedupe)
            out.append({'kind': doc.get('kind'), 'name': doc.get('name'), 'repo': doc.get('repo') or '',
                        'description': doc.get('description') or '', 'path': doc.get('path') or '',
                        'money_lane': doc.get('money_lane') or 'none', 'score': round(score, 3)})
            if len(out) >= k:
                break
        return out
    except Exception:  # noqa: BLE001 - search must never break MARVIN
        return []


def summary(paths=None):
    """{repos, skills_installed, skills_indexed, cards, digests, diagrams, updated, top_money, note}."""
    reg = load(paths=paths)
    counts = reg.get('counts') or {}
    notes = list(reg.get('notes') or [])
    repos, digests = counts.get('repos', 0), counts.get('digests', 0)
    if repos and digests < repos:
        notes.append('%d/%d repos have a DIGEST.txt so far; counts refresh automatically as the digest job adds more.'
                     % (digests, repos))
    return {'repos': repos, 'skills_installed': counts.get('skills_installed', 0),
            'skills_indexed': counts.get('skills_indexed', 0), 'cards': counts.get('cards', 0),
            'digests': digests, 'diagrams': counts.get('diagrams', 0),
            'updated': reg.get('patched_at') or reg.get('built_at'),
            'top_money': [{'name': t.get('name'), 'why': t.get('why'), 'run': t.get('run')}
                          for t in reg.get('top_money') or []],
            'note': ' '.join(notes) or None}


def detail(name_or_repo, paths=None):
    """Full stored record (run command, digest flags, card, MONEY-RUNNABLE notes) for one repo/skill/card."""
    want = str(name_or_repo or '').strip().lower()
    if not want:
        return None
    docs = load(paths=paths).get('docs', [])
    order = {'repo': 0, 'card': 1, 'skill': 2}
    matches = [d for d in docs if want in (str(d.get('repo', '')).lower(), str(d.get('name', '')).lower(),
                                           str(d.get('repo', '')).lower().replace('/', '__'))]
    if not matches:
        return None
    doc = dict(min(matches, key=lambda d: order.get(d.get('kind'), 9)))
    doc.pop('terms', None)
    if doc.get('kind') == 'repo':
        base = Path(doc.get('path', '')) / '_nexen'
        doc['digest_path'] = str(base / 'DIGEST.txt') if doc.get('digest') else None
        doc['diagram_path'] = str(base / 'DIAGRAM.md') if doc.get('diagram') else None
    return doc


def context_for(query, k=5, kinds=None, max_chars=1800, paths=None):
    """Compact text block of the best matches, for dropping into a local-LLM prompt."""
    lines = []
    for hit in search(query, k, kinds, paths=paths):
        extra = ''
        if hit['kind'] == 'repo':
            full = detail(hit['repo'], paths=paths) or {}
            if full.get('run'):
                extra = ' | run: ' + full['run']
        lines.append('- [%s] %s (%s) lane=%s: %s%s' % (hit['kind'], hit['name'], hit['repo'] or '-',
                                                       hit['money_lane'], _clip(hit['description'], 180), extra))
    return _clip('\n'.join(lines), max_chars) if len('\n'.join(lines)) > max_chars else '\n'.join(lines)


# ----------------------------------------------------------------------------- routes
def register(app, db=None):
    """GET /api/arsenal/search?q=&k=&kinds= -> list (search() rows); GET /api/arsenal/summary -> summary()."""

    @app.get('/api/arsenal/search')
    def arsenal_search(q: str = '', k: int = 8, kinds: str = ''):
        try:
            return search(q[:300], max(1, min(k, 50)), [x for x in kinds.split(',') if x.strip()] or None)
        except Exception:  # noqa: BLE001
            return []

    @app.get('/api/arsenal/summary')
    def arsenal_summary():
        try:
            return summary()
        except Exception as exc:  # noqa: BLE001
            return {'repos': 0, 'skills_installed': 0, 'skills_indexed': 0, 'cards': 0, 'digests': 0,
                    'diagrams': 0, 'updated': None, 'top_money': [],
                    'note': 'Arsenal registry unavailable (%s).' % type(exc).__name__}

    return app


if __name__ == '__main__':
    import sys
    t0 = time.perf_counter()
    reg = load(force='--rebuild' in sys.argv)
    print(json.dumps({'load_s': round(time.perf_counter() - t0, 3), 'build_ms': reg.get('build_ms'),
                      'counts': reg.get('counts'), 'lanes': reg.get('lanes')}, indent=1))
    print(json.dumps(summary(), indent=1, ensure_ascii=False))
    query = ' '.join(a for a in sys.argv[1:] if not a.startswith('--'))
    if query:
        for row in search(query, 5):
            print(json.dumps(row, ensure_ascii=False))

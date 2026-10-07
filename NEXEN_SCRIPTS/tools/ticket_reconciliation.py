"""Reconcile reviewed source requirements with the existing canonical Tracker.

Historical intake records are catalogued, never automatically dispatched. Apply
uses existing idempotent seed keys and never changes the status of an old task.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing, contextmanager
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

APP = Path('H:/NEXEN/v1/app')
SANITIZER = Path('H:/NEXEN/worktrees/dolonia-handoff-20261003/tools/source_intake/intake_prompt_queue.py')
LANES = {'A': 'Context, memory and tasks', 'B': 'Revenue and workflows',
         'C': 'MARVIN, dashboard and voice', 'D': 'Workers and compute',
         'X': 'Integration, QA and governance'}


def load_sanitizer():
    spec = importlib.util.spec_from_file_location('existing_intake_sanitizer', SANITIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.sanitize


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def validate_crosswalk(source_rows, crosswalk):
    expected={}
    for row in source_rows:
        for ident in row.get('member_intake_ids',[row['intake_id']]):
            if ident in expected:
                raise ValueError('duplicate original source member')
            expected[ident]=row['intake_id']
    actual={}
    for row in crosswalk:
        if row['intake_id'] in actual:
            raise ValueError('duplicate crosswalk source member')
        actual[row['intake_id']]=row['ticket_id']
    if expected!=actual:
        raise ValueError('exactly-once source member crosswalk mismatch')
    return len(actual)


def identity(text):
    return ' '.join(str(text).casefold().split())


def category(row):
    if row.get('lane') in LANES:
        return row['lane']
    hint = str(row.get('domain_hint') or row.get('category') or '')
    text = hint + ' ' + str(row.get('title') or row.get('text') or '')
    for lane, pattern in [('D', r'pc2|worker|compute|gpu|ollama|model routing|lease|coding.loop'),
                          ('C', r'marvin|marvin|dashboard|discord|voice|hud|gui|3d|computer.view'),
                          ('B', r'money|revenue|clip|campaign|dropship|n8n|youtube|persona|workflow|shop|lumipaw|affiliate'),
                          ('A', r'memory|context|source|vault|ingest|ticket|task|knowledge|packet|transcript')]:
        if re.search(pattern, text, re.I):
            return lane
    return 'X'


def validate_requirements(rows):
    if not isinstance(rows, list):
        raise ValueError('requirements must be a list')
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('requirement must be an object')
        ident = row.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}', ident) or ident in seen:
            raise ValueError('invalid or duplicate requirement ID')
        seen.add(ident)
        if not isinstance(row.get('title'), str) or not row['title'].strip():
            raise ValueError('requirement title required')
        if row.get('lane') not in LANES or row.get('priority') not in {'urgent','high','normal','low'}:
            raise ValueError('invalid lane or priority')
        if row.get('status') not in {'planned', 'blocked'}:
            raise ValueError('new source requirements must stay planned or blocked')
        refs, checks = row.get('source_refs'), row.get('acceptance_checks')
        if not isinstance(refs, list) or not refs or not all(isinstance(r,dict) and r.get('path') and r.get('locator') for r in refs):
            raise ValueError('exact source path and locator required')
        if not isinstance(checks,list) or not checks or not all(isinstance(c,str) and c.strip() for c in checks):
            raise ValueError('independent acceptance criteria required')
        ids = row.get('existing_task_ids', [])
        if not isinstance(ids,list) or any(type(i) is not int or i <= 0 for i in ids):
            raise ValueError('invalid canonical task reference')
        if len(json.dumps(row,ensure_ascii=False)) > 24000:
            raise ValueError('requirement exceeds bounded size')
    return rows


def canonical_snapshot(path):
    p = Path(path).resolve()
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro', uri=True, timeout=5)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute('''SELECT r.id,r.text,r.status,d.seed_key,
            coalesce(d.priority,'normal') priority,coalesce(d.next_step,'') next_step
            FROM hub_requests r LEFT JOIN task_details d ON d.request_id=r.id ORDER BY r.id''')]


def plan(rows, canonical):
    validate_requirements(rows)
    by_id = {r['id']:r for r in canonical}
    by_seed = {r['seed_key']:r for r in canonical if r.get('seed_key')}
    by_title = {}
    for r in canonical:
        by_title.setdefault(identity(r['text']), []).append(r)
    result = []
    seen_titles={}
    for row in rows:
        title_key=identity(row['title'])
        if title_key in seen_titles and not row.get('distinct_scope_reason'):
            raise ValueError('duplicate incoming title requires explicit merge or distinct scope: '+row['id'])
        seen_titles[title_key]=row['id']
        missing = set(row.get('existing_task_ids', [])) - by_id.keys()
        if missing:
            raise ValueError('unknown canonical task reference: '+str(sorted(missing)))
        seed = 'v3-reconciled:' + row['id']
        if row.get('import_action')=='do_not_import':
            result.append({**row,'seed_key':seed,'canonical_task_ids':[],
                           'action':'hold-source-only','match_type':None})
            continue
        matches = row.get('existing_task_ids', [])
        match_type = 'explicit-reference'
        if not matches and seed in by_seed:
            if by_seed[seed]['text']!=task_body(row):
                raise ValueError('seed replay specification changed; explicit review/update required: '+row['id'])
            matches = [by_seed[seed]['id']]
            match_type = 'seed-key'
        if not matches and len(by_title.get(title_key,[])) > 1:
            raise ValueError('ambiguous canonical title; explicit task reference required: '+row['id'])
        if not matches and len(by_title.get(title_key,[])) == 1:
            matches = [by_title[title_key][0]['id']]
            match_type = 'exact-title'
        result.append({**row,'seed_key':seed,'canonical_task_ids':matches,
                       'action':'reuse' if matches else 'create',
                       'match_type':match_type if matches else None})
    return result


class ExistingDB:
    """Only the connection contract expected by the existing Tracker."""
    def __init__(self,path):
        self.path = Path(path).resolve()
    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
    def rows(self, sql, params=()):
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql,params)]
    def scalar(self, sql, params=()):
        with self.connect() as con:
            r=con.execute(sql,params).fetchone()
            return r[0] if r else None


def task_body(row):
    refs='\n'.join(str(r['path'])+' | '+str(r['locator']) for r in row['source_refs'])
    checks='\n'.join('- '+c for c in row['acceptance_checks'])
    text=(row['title']+'\n\nNEXEN V3 requirement '+row['id']+'; lane '+row['lane']+
          '; parent #142. Prepared specification; no execution or completion claimed.\n'+
          'Acceptance:\n'+checks+'\nSources:\n'+refs+'\n'+str(row.get('notes','')))
    if len(text)>12000:
        raise ValueError('task exceeds existing Tracker text contract')
    return text.strip()


def apply_plan(rows, db_path, tracker_factory=None):
    # Validate ALL references/texts before any write. Tracker seeds make recovery
    # after partial interruption safe; there is no retry loop or completion mark.
    items=plan(rows,canonical_snapshot(db_path))
    for item in items:
        task_body(item)
    if tracker_factory is None:
        sys.path.insert(0,str(APP))
        from task_tracking import Tracker,TaskCreate
        tracker=Tracker(ExistingDB(db_path))
    else:
        tracker,TaskCreate=tracker_factory()
    results=[]
    for row in items:
        if row['action']!='create':
            results.append(row)
            continue
        body=TaskCreate(text=task_body(row),priority=row['priority'],
                        next_step='Run reviewed acceptance checks for '+row['id']+'; preserve STOP and exact approval gates.')
        task_id=tracker.create(body,seed_key=row['seed_key'],initial_status=row['status'])
        results.append({**row,'canonical_task_ids':[task_id]})
    after={r['id']:r for r in canonical_snapshot(db_path)}
    for row in results:
        for ident in row['canonical_task_ids']:
            if ident not in after:
                raise ValueError('canonical readback missing')
        if row['action']=='create' and after[row['canonical_task_ids'][0]]['seed_key']!=row['seed_key']:
            raise ValueError('canonical readback seed mismatch')
    return results


def catalogue(source_rows, canonical, requirements):
    out=[]
    for r in canonical:
        out.append({'id':'TASK-'+str(r['id']),'namespace':'canonical-task','title':str(r['text']).splitlines()[0],
                    'lane':category(r),'status':r['status'],'evidence_status':'canonical-state',
                    'source':str(APP/'data/nexen.db')+' | hub_requests.id='+str(r['id'])})
    seen=set()
    for r in source_rows:
        ident=r['intake_id']
        if ident in seen:
            raise ValueError('duplicate intake ID; use existing consolidated crosswalk')
        seen.add(ident)
        out.append({'id':ident,'namespace':'source-evidence','title':'[PRIVATE: inspect local source]' if r.get('private') else str(r.get('title') or ident),
                    'lane':category(r),'category':r.get('category',r.get('kind','source')),'requirement_group_id':r.get('requirement_group_id'),
                    'status':'hold-variant' if r.get('source_variant_conflict') else 'hold-context' if r.get('kind')=='source-context' else 'unqualified',
                    'evidence_status':'source-only','source':str(r.get('src_path',''))+' | '+str(r.get('src_locator','')),
                    'original_member_ids':r.get('member_intake_ids',[ident]),
                    'source_relationships':[{'intake_id':s.get('intake_id'),'path':s.get('src_path'),'locator':s.get('src_locator')} for s in r.get('source_members',[])],
                    'variant_ids':[s.get('intake_id') for s in r.get('source_variants',[])],
                    'hold_reason':'private source retained locally' if r.get('private') else str(r.get('notes','')) if r.get('kind')=='source-context' else ''})
    for r in requirements:
        out.append({'id':r['id'],'namespace':'reviewed-requirement','title':r['title'],'lane':r['lane'],
                    'status':r['status'],'evidence_status':'prepared','canonical_task_ids':r.get('canonical_task_ids',[]),
                    'source':'; '.join(str(s['path'])+' | '+str(s['locator']) for s in r['source_refs'])})
    return out


def write_report(out, source_rows, canonical, requirements, sanitizer, inventory=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=catalogue(source_rows,canonical,requirements)
    secondary=(inventory or {}).get('secondary_tracker',{}).get('tickets',[])
    classified={r['id']:r for r in (inventory or {}).get('canonical',{}).get('tasks',[])}
    new_safe={ident:r['title'] for r in requirements for ident in r.get('canonical_task_ids',[])}
    for row in rows:
        if row['namespace']=='canonical-task':
            ident=int(row['id'].split('-')[1]);known=classified.get(ident)
            row['title']=('[PRIVATE: inspect canonical task locally]' if known.get('private') else known.get('title','[inspect canonical task locally]')) if known else new_safe.get(ident,'[UNCLASSIFIED PRIVATE: inspect canonical task locally]')
    for r in secondary:
        rows.append({'id':r['id'],'namespace':'secondary-worker-ticket','title':r.get('title',''),
                     'lane':r['lane'] if r.get('lane') in LANES else category(r),'status':r['status'],
                     'evidence_status':'secondary-state; lease '+('active' if r.get('lease_active') else 'inactive'),
                     'source':str((inventory or {})['secondary_tracker']['database'])+' | tickets.id='+r['id']})
    rows=sanitizer(rows)
    counts={'canonical_tasks':len(canonical),'source_evidence_groups':len(source_rows),
            'reviewed_requirements':len(requirements),'secondary_worker_tickets':len(secondary),'catalogue_rows':len(rows),
            'canonical_statuses':dict(Counter(r['status'] for r in canonical)),
            'reviewed_lanes':dict(Counter(r['lane'] for r in requirements)),
            'source_variants_held':sum(bool(r.get('source_variant_conflict')) for r in source_rows)}
    (out/'TICKET-CATALOG.json').write_text(json.dumps({'counts':counts,'rows':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'TICKET-CATALOG.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','namespace','lane','status','evidence_status','title','source','canonical_task_ids'],extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)
    (out/'CANONICAL-CROSSWALK.json').write_text(json.dumps(sanitizer(requirements),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    data=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html=r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NEXEN V3 tickets</title>
    <style>body{background:#0d1117;color:#e6edf3;font:15px system-ui;padding:24px}h1{color:#ff5757}input,select{padding:10px;background:#161b22;color:#fff;border:1px solid #444;border-radius:6px;margin:6px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #333}small{color:#adb8c4}a{color:#ff9292}.title{max-width:650px}#count{margin:15px}</style>
    <h1>NEXEN V3 ticket reconciliation</h1><p>Canonical tasks, reviewed requirements, and original source evidence retain separate IDs. Source counts do not mean completed features.</p>
    <input id="q" placeholder="Search ID, title or source" size="45"><select id="ns"><option value="">All namespaces</option><option>canonical-task</option><option>secondary-worker-ticket</option><option>reviewed-requirement</option><option>source-evidence</option></select><select id="lane"><option value="">All lanes</option><option>A</option><option>B</option><option>C</option><option>D</option><option>X</option></select><select id="status"><option value="">All statuses</option></select><div id="count"></div><table><thead><tr><th>ID / lane</th><th>Status</th><th>Ticket / source</th></tr></thead><tbody id="body"></tbody></table><button id="more">Show next 200</button>
    <script>const rows=__DATA__;let cap=200;const $=id=>document.getElementById(id);for(const s of [...new Set(rows.map(r=>r.status))].sort()){const o=document.createElement('option');o.value=s;o.textContent=s;$('status').append(o)}
    function render(){const q=$('q').value.toLowerCase();const found=rows.filter(r=>(!$('ns').value||r.namespace===$('ns').value)&&(!$('lane').value||r.lane===$('lane').value)&&(!$('status').value||r.status===$('status').value)&&JSON.stringify(r).toLowerCase().includes(q));$('count').textContent=found.length+' matching rows / '+rows.length+' total; displaying '+Math.min(cap,found.length);$('body').replaceChildren();for(const r of found.slice(0,cap)){const tr=document.createElement('tr');for(const v of [r.id+' Â· '+r.lane,r.status+' / '+r.namespace]){const td=document.createElement('td');td.textContent=v;tr.append(td)}const td=document.createElement('td'),title=document.createElement('strong');title.textContent=r.title;td.append(title);if(r.canonical_task_ids?.length){const related=document.createElement('div');related.textContent='Canonical #'+r.canonical_task_ids.join(', #');td.append(related)}const details=document.createElement('details'),summary=document.createElement('summary'),source=document.createElement('small');summary.textContent='Source and evidence';source.textContent=r.source+'\n'+r.evidence_status;source.style.whiteSpace='pre-wrap';source.style.overflowWrap='anywhere';details.append(summary,source);td.append(details);tr.append(td);$('body').append(tr)}$('more').hidden=cap>=found.length}for(const id of ['q','ns','lane','status'])$(id).addEventListener('input',()=>{cap=200;render()});$('more').onclick=()=>{cap+=200;render()};render();</script></html>'''.replace('__DATA__',data)
    (out/'NEXEN-V3-TICKETS.html').write_text(html,encoding='utf-8')
    return counts


def main():
    p=argparse.ArgumentParser();p.add_argument('--requirements',required=True);p.add_argument('--source',required=True)
    p.add_argument('--database',default=str(APP/'data/nexen.db'));p.add_argument('--output',required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--inventory')
    p.add_argument('--crosswalk',required=True)
    p.add_argument('--publish-secondary-snapshot',action='store_true')
    a=p.parse_args();sanitize=load_sanitizer();rows=sanitize(read_json(a.requirements)['requirements']);validate_requirements(rows)
    source_rows=read_jsonl(a.source)
    inventory=read_json(a.inventory) if a.inventory else None
    with Path(a.crosswalk).open(encoding='utf-8-sig',newline='') as stream:
        crosswalk=list(csv.DictReader(stream))
    validate_crosswalk(source_rows,crosswalk)
    # Full catalogue/report inputs validated before any live write.
    preview=plan(rows,canonical_snapshot(a.database))
    catalogue(source_rows,canonical_snapshot(a.database),preview)
    if inventory is not None:
        for ticket in inventory.get('canonical',{}).get('tasks',[]):
            if type(ticket.get('id')) is not int or type(ticket.get('private')) is not bool:
                raise ValueError('canonical privacy classification required')
        for ticket in inventory.get('secondary_tracker',{}).get('tickets',[]):
            if not ticket.get('id') or not ticket.get('status'):
                raise ValueError('malformed secondary inventory')
    if a.publish_secondary_snapshot:
        if not a.apply or inventory is None:
            raise ValueError('secondary publication requires apply and validated inventory')
        secondary_db=Path(inventory['secondary_tracker']['database']).resolve()
        with closing(sqlite3.connect(secondary_db.as_uri()+'?mode=ro',uri=True,timeout=5)) as con:
            actual_ids={r[0] for r in con.execute('SELECT id FROM tickets')}
        if actual_ids!={r['id'] for r in inventory['secondary_tracker']['tickets']}:
            raise ValueError('secondary inventory stale; reread before any write')
    if a.apply:
        sys.path.insert(0,str(APP))
        from coding_ownership import LeaseStore
        leases=LeaseStore(a.database)
        owner='codex-ticket-reconciliation-20261003'
        lease=leases.acquire(142,'Ticket reconciliation only; existing Tracker seed imports and report artifacts',owner,ttl_seconds=900)
        if not lease['acquired']:
            raise ValueError('another canonical implementation owner is active')
        try:
            requirements=apply_plan(rows,a.database)
            if a.publish_secondary_snapshot:
                if inventory is None:raise ValueError('secondary inventory required')
                sys.path.insert(0,'H:/NEXEN/tracker')
                import tracker as secondary
                secondary_db=Path(inventory['secondary_tracker']['database']).resolve()
                with closing(sqlite3.connect(secondary_db.as_uri()+'?mode=ro',uri=True,timeout=5)) as con:
                    con.row_factory=sqlite3.Row
                    published=secondary.publish_snapshot(con,secondary_db.parent/'sync','pc1')
                    readback=secondary.read_snapshot(published)
                    if {r['id'] for r in readback['tickets']}!={r['id'] for r in inventory['secondary_tracker']['tickets']}:
                        raise ValueError('secondary snapshot count changed; reread current inventory')
        finally:
            if not leases.release(lease['token'],owner,'Ticket reconciliation finished or safely interrupted; no task completion or dispatch'):
                raise ValueError('canonical ownership release failed')
    else:
        requirements=plan(rows,canonical_snapshot(a.database))
    counts=write_report(a.output,source_rows,canonical_snapshot(a.database),requirements,sanitize,inventory)
    shutil.copy2(a.crosswalk,Path(a.output)/'SOURCE-CROSSWALK.csv')
    print(json.dumps({'mode':'applied' if a.apply else 'prepared','counts':counts,
                      'actions':dict(Counter(r['action'] for r in requirements))},indent=2))


if __name__=='__main__':
    main()


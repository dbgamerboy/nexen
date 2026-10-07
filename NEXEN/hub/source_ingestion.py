"""Bounded, resumable local note ingestion from the existing metadata census.

Source text is evidence. This module never enqueues model analysis or execution.
"""
import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from memory_bridge import redact, _reject_links
from text_utils import chunk_text, utcnow

BASE=Path(__file__).resolve().parent
MANIFEST=BASE/'data/source-roots.json'
TEXT={'.md','.markdown','.txt','.json','.jsonl','.csv','.tsv'}
ARCHIVES={'.rar','.zip','.7z','.tar','.gz'}
SKIP={'.git','.venv','venv','node_modules','__pycache__','.cache','cache','caches','temp','tmp','models','model','blobs','downloads','checkpoints','weights','logs','generated_workflows','test-work','work','dist','build','harnesses','library','nexen_tools'}


class PassDeadline(RuntimeError):
    """This pass yielded; durable cursors and pending work remain resumable."""


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise PassDeadline('time_budget')


@contextmanager
def bounded_sql(connection, deadline):
    check_deadline(deadline)
    remaining = max(1, int((deadline - time.monotonic()) * 1000))
    connection.execute('PRAGMA busy_timeout=%d' % min(250, remaining))
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
    try:
        yield connection
        check_deadline(deadline)
    except sqlite3.OperationalError as error:
        code = getattr(error, 'sqlite_errorcode', None)
        if code in (sqlite3.SQLITE_INTERRUPT, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise PassDeadline('database_busy' if code != sqlite3.SQLITE_INTERRUPT else 'time_budget') from error
        raise


class SourceIngestion:
    def __init__(self,db,manifest=MANIFEST,census=None):
        self.db=db
        self.manifest=Path(manifest)
        self.census=Path(census or BASE/'data/census/census.sqlite3')
        self.settings=json.loads(self.manifest.read_text(encoding='utf-8-sig'))
        with db.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS source_roots(path TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,last_discovered_at TEXT);
            CREATE TABLE IF NOT EXISTS source_queue(path TEXT PRIMARY KEY,root TEXT NOT NULL,state TEXT NOT NULL,reason TEXT,expected_size INTEGER,expected_mtime INTEGER,file_id INTEGER,sha256 TEXT,read_bytes INTEGER DEFAULT 0,text_chars INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS source_pending ON source_queue(state,root,updated_at);
            CREATE TABLE IF NOT EXISTS source_passes(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,stats_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_ingestion_state(id INTEGER PRIMARY KEY CHECK(id=1),reconcile_cursor INTEGER NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO source_ingestion_state(id) VALUES(1);''')
            c.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in c.execute('PRAGMA table_info(source_roots)')}
            for name, kind in (('scan_path', 'TEXT'), ('scan_highwater', 'INTEGER')):
                if name not in columns:
                    c.execute(f'ALTER TABLE source_roots ADD COLUMN {name} {kind}')

    @contextmanager
    def _connect_db(self, deadline):
        check_deadline(deadline)
        try:
            with self.db.connect() as c, bounded_sql(c, deadline):
                yield c
        except sqlite3.OperationalError as error:
            # The DB adapter commits after bounded_sql exits. Its commit uses
            # the same busy/progress limits and must also yield on contention.
            if getattr(error,'sqlite_errorcode',None) in (sqlite3.SQLITE_INTERRUPT,sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise PassDeadline('database_busy') from error
            raise

    def classify(self,path):
        p=Path(path)
        parts={v.lower() for v in p.parts}
        if parts & SKIP:return 'excluded','cache_model_dependency_or_generated'
        name=p.name.lower()
        if name in {'state.json','status.json','manifest.json','package.json','package-lock.json','requirements.txt'} or name.endswith(('_state.json','_port.txt')) or name.startswith(('events.','errors.')):
            return 'excluded','generated_runtime_state_or_dependency_metadata'
        if p.name.lower().startswith('.env') or any(word in p.stem.lower() for word in ('credential','secret','api_key','token','password','auth-cache')):
            return 'excluded','credential_configuration'
        if p.suffix.lower() in ARCHIVES:return 'pending_archive','archive_requires_bounded_parser'
        if p.suffix.lower() not in TEXT:return 'excluded','unsupported_content_type'
        return 'pending','approved_text_evidence'

    def discover(self,per_root=250,deadline=None):
        deadline = time.monotonic() + 20 if deadline is None else deadline
        check_deadline(deadline)
        if not self.census.is_file():return {'status':'census_unavailable','observed':0}
        observed=scanned=0
        limit=max(1,min(per_root,100))
        with closing(sqlite3.connect(self.census.resolve().as_uri()+'?mode=ro',uri=True,timeout=.25)) as source, bounded_sql(source,deadline):
            source.execute('PRAGMA query_only=ON');source.execute('PRAGMA temp_store=MEMORY')
            highwater=source.execute('SELECT coalesce(max(rowid),0) FROM files').fetchone()[0]
            for root in self.settings['roots']:
                check_deadline(deadline)
                if not root.get('enabled'):continue
                path=str(Path(root['path']))
                with self._connect_db(deadline) as c:
                    c.execute('INSERT OR IGNORE INTO source_roots(path) VALUES(?)',(path,))
                    cursor,scan_path,scan_highwater=c.execute('SELECT cursor,scan_path,scan_highwater FROM source_roots WHERE path=?',(path,)).fetchone()
                if scan_highwater is None and cursor>=highwater:continue
                sweep_highwater=highwater if scan_highwater is None else scan_highwater
                prefix=path.rstrip('\\/')+'\\'
                # Page through the existing path index. Filtering by rowid before
                # LIMIT or sorting by rowid scans/sorts an entire root subtree.
                comparison='>' if scan_path else '>='
                lower=scan_path or prefix
                # rowid/path are covered by the path index. Fetching size/time
                # for already-seen rows would add a random disk read per entry.
                rows=source.execute(f'SELECT rowid,path FROM files WHERE path{comparison}? AND path<? ORDER BY path LIMIT ?',(lower,prefix+'\uffff',limit)).fetchall()
                fresh=[row for row in rows if cursor<row[0]<=sweep_highwater]
                metadata={}
                if fresh:
                    marks=','.join('?' for _ in fresh)
                    metadata={row[0]:row[1:] for row in source.execute(f'SELECT rowid,size,modified_ns FROM files WHERE rowid IN ({marks})',[row[0] for row in fresh])}
                with self._connect_db(deadline) as c:
                    for ident,name in fresh:
                        check_deadline(deadline)
                        size,mtime=metadata[ident]
                        state,reason=self.classify(name)
                        if state=='pending' and size>1024*1024:state,reason='pending_large','file_exceeds_1_MiB_bounded_read'
                        c.execute('''INSERT INTO source_queue(path,root,state,reason,expected_size,expected_mtime,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO NOTHING''',(name,path,state,reason,size,mtime,utcnow()))
                    if len(rows)<limit:
                        c.execute('UPDATE source_roots SET cursor=?,scan_path=NULL,scan_highwater=NULL,last_discovered_at=? WHERE path=?',(sweep_highwater,utcnow(),path))
                    else:
                        c.execute('UPDATE source_roots SET scan_path=?,scan_highwater=?,last_discovered_at=? WHERE path=?',(rows[-1][1],sweep_highwater,utcnow(),path))
                observed+=len(fresh)
                scanned+=len(rows)
        return {'status':'snapshot_progress','observed':observed,'metadata_scanned':scanned,'census_may_still_be_growing':True}

    def discover_top_level(self,deadline=None):
        """Catch original root notes added after the census snapshot; no recursion."""
        deadline = time.monotonic() + 20 if deadline is None else deadline
        observed=0
        for root in self.settings['roots']:
            check_deadline(deadline)
            if not root.get('enabled'):continue
            path=Path(root['path'])
            try:
                _reject_links(path)
                with os.scandir(path) as entries:
                    candidates=[]
                    for i,entry in enumerate(entries):
                        check_deadline(deadline)
                        if i>=150:break
                        if entry.is_file(follow_symlinks=False):candidates.append(Path(entry.path))
                with self._connect_db(deadline) as c:
                    for p in candidates:
                        check_deadline(deadline)
                        st=p.stat();state,reason=self.classify(p)
                        if state=='pending' and st.st_size>1024*1024:state,reason='pending_large','file_exceeds_1_MiB_bounded_read'
                        c.execute('INSERT OR IGNORE INTO source_queue(path,root,state,reason,expected_size,expected_mtime,updated_at) VALUES(?,?,?,?,?,?,?)',(str(p),str(path),state,reason,st.st_size,st.st_mtime_ns,utcnow()))
                        observed+=1
            except (OSError,ValueError):continue
        return observed

    def reconcile_exclusions(self,deadline=None,limit=250):
        """Remove only this worker's generated-text chunks after classification tightens."""
        deadline = time.monotonic() + 20 if deadline is None else deadline
        with self._connect_db(deadline) as c:
            cursor=c.execute('SELECT reconcile_cursor FROM source_ingestion_state WHERE id=1').fetchone()[0]
            rows=c.execute('SELECT rowid,path,state,file_id FROM source_queue WHERE rowid>? ORDER BY rowid LIMIT ?',(cursor,max(1,min(limit,1000)))).fetchall()
            for row in rows:
                check_deadline(deadline)
                if row['state'] not in ('pending','indexed','indexed_partial'):continue
                state,reason=self.classify(row['path'])
                if state!='excluded':continue
                if row['file_id'] is not None:
                    c.execute('DELETE FROM chunks WHERE file_id=?',(row['file_id'],))
                    c.execute("UPDATE files SET extraction_status='excluded_generated',text_chars=0 WHERE id=?",(row['file_id'],))
                c.execute('UPDATE source_queue SET state=?,reason=?,text_chars=0,updated_at=? WHERE path=?',(state,reason,utcnow(),row['path']))
            c.execute('UPDATE source_ingestion_state SET reconcile_cursor=? WHERE id=1',(rows[-1][0] if rows else 0,))
        return {'metadata_examined':len(rows),'resumable':True}

    def _read_one(self,item,remaining,deadline=None):
        deadline = time.monotonic() + 20 if deadline is None else deadline
        check_deadline(deadline)
        p=Path(item['path']);root=Path(item['root']).resolve()
        _reject_links(p)
        p.resolve().relative_to(root)
        state,reason=self.classify(p)
        if state!='pending':return {'state':state,'reason':reason,'read_bytes':0}
        st=p.stat()
        if st.st_size>min(1024*1024,remaining):return {'state':'pending_large','reason':'current_size_exceeds_read_budget','read_bytes':0}
        # Read once, bounded by the verified size. A changed file is retried explicitly.
        with p.open('rb') as stream:raw=stream.read(st.st_size)
        after=p.stat()
        if len(raw)!=st.st_size or after.st_size!=st.st_size or after.st_mtime_ns!=st.st_mtime_ns:
            return {'state':'changed','reason':'source_changed_during_read','read_bytes':len(raw)}
        sha=hashlib.sha256(raw).hexdigest()
        text=redact(raw.decode('utf-8-sig',errors='replace')).replace('\x00',' ')
        partial=len(text)>180000
        text=text[:180000]
        status='source_partial' if partial else ('ok' if text.strip() else 'empty')
        with self._connect_db(deadline) as c:
            c.execute('''INSERT INTO files(path,size_bytes,mtime,sha256,extension,indexed_at,extraction_status,text_chars) VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(path) DO UPDATE SET size_bytes=excluded.size_bytes,mtime=excluded.mtime,sha256=excluded.sha256,extension=excluded.extension,indexed_at=excluded.indexed_at,extraction_status=excluded.extraction_status,text_chars=excluded.text_chars''',(str(p),st.st_size,st.st_mtime,sha,p.suffix.lower(),utcnow(),status,len(text)))
            fid=c.execute('SELECT id FROM files WHERE path=?',(str(p),)).fetchone()[0]
            c.execute('DELETE FROM chunks WHERE file_id=?',(fid,))
            for i,chunk in enumerate(chunk_text(text)):
                check_deadline(deadline)
                c.execute('INSERT INTO chunks(file_id,chunk_index,text,created_at) VALUES(?,?,?,?)',(fid,i,chunk,utcnow()))
        return {'state':'indexed_partial' if partial else 'indexed','reason':'local_redacted_text_only_no_execution','read_bytes':len(raw),'text_chars':len(text),'file_id':fid,'sha256':sha}

    def run_pass(self,max_files=25,max_bytes=4*1024*1024,seconds=20,discover=True):
        from file_census import SingleWriter
        started=time.monotonic();duration=max(1,min(float(seconds),60));deadline=started+duration
        work_deadline=deadline-min(2,duration*.2)  # Reserve time for the durable pass receipt.
        state_dir=self.manifest.parent/'source-ingestion';state_dir.mkdir(parents=True,exist_ok=True)
        with SingleWriter(state_dir):
            stats={'files_attempted':0,'read_files':0,'read_bytes':0,'indexed':0,'errors':0,'execution_jobs_queued':0,'network_submissions':0,'deadline_exceeded':False}
            limit=max(1,min(int(max_files),25));budget=max(0,min(int(max_bytes),4*1024*1024))
            try:
                if discover:
                    discovery_deadline=min(work_deadline,time.monotonic()+min(5,duration*.25))
                    stats['phase']='discovery'
                    try:
                        stats['discovery']=self.discover(deadline=discovery_deadline)
                        stats['phase']='top_level_metadata'
                        stats['top_level_metadata_observed']=self.discover_top_level(deadline=discovery_deadline)
                    except PassDeadline as error:
                        stats.setdefault('phase_yields',{})[stats['phase']]=str(error)
                        if stats['phase']=='discovery':stats['discovery']={'status':'yielded','reason':str(error)}
                stats['phase']='reconciliation'
                try:
                    stats['reconciliation']=self.reconcile_exclusions(deadline=min(work_deadline,time.monotonic()+min(2,duration*.15)))
                except PassDeadline as error:
                    stats.setdefault('phase_yields',{})['reconciliation']=str(error)
                    stats['reconciliation']={'status':'yielded','reason':str(error)}
                # The source_pending index serves each root without sorting its
                # complete pending backlog. Root rotation still shares each pass.
                stats['phase']='pending_selection'
                roots=[str(Path(r['path'])) for r in self.settings['roots'] if r.get('enabled')]
                candidates=[]
                with self._connect_db(work_deadline) as c:
                    c.execute("UPDATE source_queue SET state='pending' WHERE state='working'")
                    pools=[c.execute("SELECT * FROM source_queue WHERE root=? AND state='pending' ORDER BY updated_at LIMIT ?",(root,limit)).fetchall() for root in roots]
                for i in range(limit):
                    candidates.extend(dict(pool[i]) for pool in pools if i<len(pool))
                stats['phase']='reading'
                for item in candidates:
                    check_deadline(work_deadline)
                    if stats['files_attempted']>=limit or stats['read_bytes']>=budget:break
                    if item['expected_size']>budget-stats['read_bytes']:continue
                    with self._connect_db(work_deadline) as c:c.execute("UPDATE source_queue SET state='working',attempts=attempts+1 WHERE path=?",(item['path'],))
                    try:result=self._read_one(item,budget-stats['read_bytes'],deadline=work_deadline)
                    except (OSError,ValueError) as exc:result={'state':'error','reason':type(exc).__name__,'read_bytes':0};stats['errors']+=1
                    with self._connect_db(work_deadline) as c:c.execute('UPDATE source_queue SET state=?,reason=?,read_bytes=?,text_chars=?,file_id=?,sha256=?,updated_at=? WHERE path=?',(result['state'],result['reason'],result['read_bytes'],result.get('text_chars',0),result.get('file_id'),result.get('sha256'),utcnow(),item['path']))
                    stats['files_attempted']+=1;stats['read_files']+=int(result['state'].startswith('indexed') or result['read_bytes']>0);stats['read_bytes']+=result['read_bytes']
                    stats['indexed']+=int(result['state'].startswith('indexed'))
                stats['phase']='finished'
            except PassDeadline as error:
                stats['deadline_exceeded']=True;stats['yield_reason']=str(error)
            stats['receipt_recorded']=False
            for _ in range(4):
                stats['elapsed_seconds']=round(time.monotonic()-started,3)
                try:
                    with self._connect_db(deadline) as c:
                        stats['receipt_recorded']=True
                        c.execute('INSERT INTO source_passes(created_at,stats_json) VALUES(?,?)',(utcnow(),json.dumps(stats)))
                    break
                except PassDeadline:
                    stats['receipt_recorded']=False
                    if time.monotonic()>=deadline:break
            coverage=self.status(deadline=deadline)
            stats['elapsed_seconds']=round(time.monotonic()-started,3)
            return {'pass':stats,'coverage':coverage}

    def status(self,deadline=None):
        deadline=time.monotonic()+2 if deadline is None else deadline
        counts=[];reasons=[];last=None;available=True
        try:
            with self._connect_db(deadline) as c:
                counts=[dict(r) for r in c.execute('SELECT root,state,count(*) files,sum(read_bytes) read_bytes,sum(text_chars) text_chars FROM source_queue GROUP BY root,state')]
                reasons=[dict(r) for r in c.execute('SELECT state,reason,count(*) files FROM source_queue GROUP BY state,reason')]
                last=c.execute('SELECT created_at,stats_json FROM source_passes ORDER BY id DESC LIMIT 1').fetchone()
        except PassDeadline:
            counts=[];reasons=[];last=None;available=False
        return {'available':available,'roots':self.settings['roots'],'coverage':counts,'reasons':reasons,'last_pass':{'created_at':last[0],**json.loads(last[1])} if last else None,'scope':'Only classified census entries and explicitly indexed text; census names do not mean content was read. Large files and archives remain pending. Indexed sources are not executed.','complete':False,'egress':'none','limits':{'files':25,'bytes':4194304,'bytes_per_file':1048576,'text_chars_per_file':180000}}


def register(app,db):
    worker=SourceIngestion(db)
    @app.get('/api/sources/status')
    def status():return worker.status()
    return worker


if __name__=='__main__':
    from nexen import DB
    parser=argparse.ArgumentParser();parser.add_argument('--status',action='store_true');args=parser.parse_args()
    worker=SourceIngestion(DB(str(BASE/'data/nexen.db')))
    print(json.dumps(worker.status() if args.status else worker.run_pass(),indent=2))

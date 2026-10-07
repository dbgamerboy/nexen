"""Packet97 independent canonical coding-lease tests; H: fixture databases only."""
import concurrent.futures
import hashlib
import importlib
import json
import math
import sqlite3
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

sys.dont_write_bytecode=True
ROOT=Path('H:/NEXEN/reports/v3-proof-20260930/shared-ownership')
RUN=ROOT/'test-fixtures'/('core-'+uuid.uuid4().hex[:12])
OBS={}


def fixture_database(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:
        c.executescript('''
          CREATE TABLE hub_requests(id INTEGER PRIMARY KEY,text TEXT,status TEXT,created_at TEXT);
          CREATE TABLE task_details(request_id INTEGER PRIMARY KEY,priority TEXT,due_date TEXT,
                                    updated_at TEXT,completed_at TEXT);
          CREATE TABLE task_history(id INTEGER PRIMARY KEY,request_id INTEGER NOT NULL,
                                    old_status TEXT,new_status TEXT,outcome TEXT,
                                    reminder_date TEXT,created_at TEXT NOT NULL);
        ''')
        for i,state in [(142,'in_progress'),(143,'planned'),(144,'blocked'),(145,'done')]:
            c.execute('INSERT INTO hub_requests VALUES(?,?,?,?)',(i,'isolated task',state,'2026-09-30'))
            c.execute('INSERT INTO task_details VALUES(?,?,?,?,?)',(i,'high',None,'2026-09-30',None))
    return path


def expire_fixture_lease(db):
    """Force fixture expiry without waiting900 seconds or patching production clocks."""
    with sqlite3.connect(db) as c:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        changed=0
        for name in tables:
            quoted='"'+name.replace('"','""')+'"'
            cols={r[1] for r in c.execute('PRAGMA table_info('+quoted+')')}
            if 'expires_at' in cols and ('token' in cols or 'token_hash' in cols):
                changed+=c.execute('UPDATE '+quoted+' SET expires_at=0').rowcount
        if not changed:raise AssertionError('No fixture lease expiry row found; check actual schema')


def statuses(db):
    with sqlite3.connect(db) as c:return c.execute('SELECT id,status FROM hub_requests ORDER BY id').fetchall()


class CodingOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.C=importlib.import_module('coding_ownership')
        self.db=fixture_database(RUN/self._testMethodName/'canonical.sqlite3')
        self.store=self.C.LeaseStore(self.db)
        self.before=statuses(self.db)

    def claim(self,task=142,scope='fixture',owner='owner-a',**kw):
        return self.store.acquire(task,scope,owner,**kw)

    def test_01_acquire_release_preserves_task_status(self):
        got=self.claim();self.assertIs(got['acquired'],True);self.assertTrue(got['token'])
        self.assertIn('expires_at',got);self.assertTrue(self.store.release(got['token'],'owner-a',outcome='fixture verified; no task completion'))
        self.assertEqual(statuses(self.db),self.before)
        with sqlite3.connect(self.db) as c:
            history=c.execute('SELECT old_status,new_status FROM task_history').fetchall()
        self.assertTrue(history,'lease evidence not recorded in existing history')
        self.assertTrue(all(old==new for old,new in history),'lease operation changed task status in history')

    def test_02_singleton_across_task_scope_owner(self):
        got=self.claim();self.assertTrue(got['acquired'])
        for task,scope,owner in [(142,'other','owner-b'),(143,'another','owner-c'),(142,'fixture','owner-a')]:
            with self.subTest(task=task,scope=scope,owner=owner):
                self.assertFalse(self.claim(task,scope,owner)['acquired'])
        self.assertTrue(self.store.release(got['token'],'owner-a'))

    def test_03_unknown_done_blocked_refused(self):
        for task in [999,144,145]:
            with self.subTest(task=task):
                try:r=self.claim(task)
                except (ValueError,PermissionError):continue
                self.assertFalse(r['acquired'])
        self.assertEqual(statuses(self.db),self.before)

    def test_04_wrong_owner_and_wrong_token_cannot_mutate(self):
        got=self.claim();token=got['token']
        self.assertFalse(self.store.renew(token,'owner-b'))
        self.assertFalse(self.store.release(token,'owner-b'))
        self.assertFalse(self.store.renew('not-a-real-token','owner-a'))
        self.assertFalse(self.store.release('not-a-real-token','owner-a'))
        self.assertFalse(self.claim(143,'new','owner-c')['acquired'])
        self.assertTrue(self.store.release(token,'owner-a'))

    def test_05_expired_owner_cannot_touch_successor(self):
        old=self.claim();expire_fixture_lease(self.db)
        new=self.claim(143,'successor','owner-b');self.assertTrue(new['acquired'])
        self.assertNotEqual(old['token'],new['token'])
        self.assertFalse(self.store.renew(old['token'],'owner-a'))
        self.assertFalse(self.store.release(old['token'],'owner-a',outcome='stale success'))
        self.assertFalse(self.claim(142,'third','owner-c')['acquired'])
        self.assertTrue(self.store.renew(new['token'],'owner-b'))
        self.assertTrue(self.store.release(new['token'],'owner-b'))
        self.assertEqual(statuses(self.db),self.before)

    def test_06_expired_token_cannot_resurrect_without_successor(self):
        old=self.claim();expire_fixture_lease(self.db)
        self.assertFalse(self.store.renew(old['token'],'owner-a'))
        self.assertFalse(self.store.release(old['token'],'owner-a'))
        r=self.claim(token=old['token']);self.assertFalse(r['acquired'])

    def test_07_renew_live_and_resume_same_token(self):
        got=self.claim();self.assertTrue(self.store.renew(got['token'],'owner-a',ttl_seconds=900))
        resumed=self.claim(token=got['token'])
        self.assertTrue(resumed['acquired']);self.assertEqual(resumed['token'],got['token'])
        self.assertFalse(self.claim(143,'other','owner-b')['acquired'])

    def test_08_ttl_invalid_values_cannot_create_unbounded_lease(self):
        for ttl in [-1,0,True,'900',float('inf'),float('nan'),10**12]:
            with self.subTest(ttl=str(ttl)):
                try:r=self.claim(ttl_seconds=ttl)
                except (ValueError,TypeError,OverflowError):continue
                if not r['acquired']:continue
                expiry=r['expires_at']
                if isinstance(expiry,str):
                    from datetime import datetime
                    expiry=datetime.fromisoformat(expiry.replace('Z','+00:00')).timestamp()
                self.assertTrue(math.isfinite(expiry));self.assertGreater(expiry,time.time())
                self.assertLessEqual(expiry-time.time(),86400,'TTL is not meaningfully bounded')
                self.assertTrue(self.store.release(r['token'],'owner-a'))

    def test_09_status_safe_no_raw_token(self):
        got=self.claim();encoded=json.dumps(self.store.status(),default=str)
        self.assertNotIn(got['token'],encoded,'safe status exposed a bearer lease token')
        self.assertEqual(statuses(self.db),self.before)

    def test_10_two_controller_connections_only_one_acquires(self):
        barrier=threading.Barrier(8)
        def run(i):
            s=self.C.LeaseStore(self.db);barrier.wait(timeout=5)
            return s.acquire(142 if i%2 else 143,'scope-'+str(i),'worker-'+str(i))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            got=list(pool.map(run,range(8)))
        self.assertEqual(sum(x['acquired'] is True for x in got),1)
        OBS['concurrent_controllers']={'contenders':8,'winners':1,'fixture_statuses_preserved':statuses(self.db)==self.before}

    def test_11_reopen_store_does_not_lose_live_ownership(self):
        got=self.claim();other=self.C.LeaseStore(self.db)
        self.assertFalse(other.acquire(143,'other','owner-b')['acquired'])
        self.assertTrue(other.release(got['token'],'owner-a'))
        self.assertTrue(other.acquire(143,'other','owner-b')['acquired'])

    def test_12_invalid_canonical_database_fails_closed(self):
        p=self.db.parent/'wrong.sqlite3'
        with sqlite3.connect(p) as c:c.execute('CREATE TABLE unrelated(x)')
        try:
            s=self.C.LeaseStore(p);r=s.acquire(142,'scope','owner')
        except (ValueError,RuntimeError,sqlite3.Error):return
        self.assertFalse(r['acquired'])


if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).with_name('coding_ownership.py')
    before=hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else 'MISSING'
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CodingOwnershipTests))
    data={'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),
          'failures':[{'test':str(t),'traceback':s} for t,s in result.failures],
          'errors':[{'test':str(t),'traceback':s} for t,s in result.errors],
          'observations':OBS,'fixture_root':str(RUN),'source_sha256_before':before,
          'source_sha256_after':hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else 'MISSING',
          'scope':'Only isolated H: canonical-shaped fixtures; no live canonical writes/providers/STOP changes'}
    (ROOT/'test-core-results.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    sys.exit(not result.wasSuccessful())

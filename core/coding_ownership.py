"""Canonical singleton coding ownership; fencing receipts never complete tasks."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone


class OwnershipError(ValueError):
    pass


def _label(value, name, maximum=240):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise OwnershipError("invalid " + name)
    return value


def _ttl(value):
    if type(value) is not int or not 1 <= value <= 900:
        raise OwnershipError("ttl_seconds must be an integer between 1 and 900")
    return value


def _task_id(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,17}", str(value)):
        raise OwnershipError("invalid canonical task id")
    return int(value)


class LeaseStore:
    def __init__(self, task_database):
        self.path = Path(task_database).resolve()
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                self._schema(con)
                con.execute("""CREATE TABLE IF NOT EXISTS coding_implementation_lease(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    token TEXT NOT NULL, owner TEXT NOT NULL, task_id INTEGER NOT NULL,
                    scope TEXT NOT NULL, expires_at REAL NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES hub_requests(id))""")
                con.commit()
            except Exception:
                con.rollback()
                raise

    def _connect(self):
        con = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @staticmethod
    def _schema(con):
        for table, required in {
            "hub_requests": {"id", "status"},
            "task_history": {"id", "request_id", "old_status", "new_status", "outcome", "reminder_date", "created_at"},
        }.items():
            if not required <= {r[1] for r in con.execute("PRAGMA table_info(" + table + ")")}:
                raise OwnershipError("existing canonical task schema required")

    @staticmethod
    def _history(con, row, action, outcome=""):
        task = con.execute("SELECT status FROM hub_requests WHERE id=?", (row["task_id"],)).fetchone()
        if task is None:
            raise OwnershipError("canonical task missing")
        payload = {"classification": "implementation_ownership_not_deployment", "action": action,
                   "owner_digest": hashlib.sha256(row["owner"].encode()).hexdigest(),
                   "scope_digest": hashlib.sha256(row["scope"].encode()).hexdigest(),
                   "outcome_digest": hashlib.sha256(outcome.encode()).hexdigest(), "publication": False}
        con.execute("""INSERT INTO task_history(request_id,old_status,new_status,outcome,reminder_date,created_at)
            VALUES(?,?,?,?,NULL,?)""", (row["task_id"], task["status"], task["status"],
            json.dumps(payload, sort_keys=True), datetime.now(timezone.utc).isoformat()))

    def acquire(self, task_id, scope, owner, ttl_seconds=900, token=None):
        task_id = _task_id(task_id)
        scope = _label(scope, "scope", 512)
        owner = _label(owner, "owner", 120)
        ttl = _ttl(ttl_seconds)
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                task = con.execute("SELECT status FROM hub_requests WHERE id=?", (task_id,)).fetchone()
                if task is None or task["status"] not in {"planned", "in_progress"}:
                    raise OwnershipError("known planned or in_progress canonical task required")
                row = con.execute("SELECT * FROM coding_implementation_lease WHERE singleton=1").fetchone()
                now = time.time()
                if row is not None and row["expires_at"] > now:
                    same = (isinstance(token, str) and re.fullmatch(r"[a-f0-9]{64}", token) is not None and secrets.compare_digest(token, row["token"])
                            and owner == row["owner"] and scope == row["scope"] and task_id == row["task_id"])
                    if not same:
                        con.rollback()
                        return {"acquired": False, "token": None, "expires_at": row["expires_at"]}
                    expires = now + ttl
                    con.execute("UPDATE coding_implementation_lease SET expires_at=? WHERE singleton=1", (expires,))
                    con.commit()
                    return {"acquired": True, "token": token, "expires_at": expires}
                # A supplied stale token cannot become a new generation, even without a successor.
                if token is not None:
                    con.rollback()
                    return {"acquired": False, "token": None, "expires_at": row["expires_at"] if row else None}
                token = secrets.token_hex(32)
                expires = now + ttl
                if row is not None:
                    self._history(con, row, "expired")
                con.execute("INSERT OR REPLACE INTO coding_implementation_lease VALUES(1,?,?,?,?,?)",
                            (token, owner, task_id, scope, expires))
                self._history(con, {"task_id": task_id, "owner": owner, "scope": scope}, "acquired")
                con.commit()
                return {"acquired": True, "token": token, "expires_at": expires}
            except Exception:
                con.rollback()
                raise

    @staticmethod
    def _valid(row, token, owner):
        return (row is not None and isinstance(token, str) and re.fullmatch(r"[a-f0-9]{64}", token) is not None and isinstance(owner, str)
                and secrets.compare_digest(row["token"], token) and row["owner"] == owner
                and row["expires_at"] > time.time())

    def renew(self, token, owner, ttl_seconds=900):
        ttl = _ttl(ttl_seconds)
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM coding_implementation_lease WHERE singleton=1").fetchone()
            if not self._valid(row, token, owner):
                con.rollback()
                return False
            task = con.execute("SELECT status FROM hub_requests WHERE id=?", (row["task_id"],)).fetchone()
            if task is None or task["status"] not in {"planned", "in_progress"}:
                con.rollback()
                return False
            con.execute("UPDATE coding_implementation_lease SET expires_at=? WHERE singleton=1", (time.time() + ttl,))
            con.commit()
            return True

    def release(self, token, owner, outcome="released"):
        outcome = _label(outcome, "outcome", 500)
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT * FROM coding_implementation_lease WHERE singleton=1").fetchone()
                if not self._valid(row, token, owner):
                    con.rollback()
                    return False
                self._history(con, row, "released", outcome)
                con.execute("DELETE FROM coding_implementation_lease WHERE singleton=1")
                con.commit()
                return True
            except Exception:
                con.rollback()
                raise

    def status(self):
        with closing(self._connect()) as con:
            row = con.execute("SELECT owner,task_id,scope,expires_at FROM coding_implementation_lease WHERE singleton=1").fetchone()
            if row is None:
                return {"active": False, "owner": None, "task_id": None, "scope": None, "expires_at": None}
            return {"active": row["expires_at"] > time.time(), **dict(row)}

    @contextmanager
    def guard(self, token, owner, ttl_seconds=900):
        """Hold canonical fencing through a durable transition; caller already locks durable DB."""
        ttl = _ttl(ttl_seconds)
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT * FROM coding_implementation_lease WHERE singleton=1").fetchone()
                if not self._valid(row, token, owner):
                    raise OwnershipError("canonical implementation ownership lost")
                task = con.execute("SELECT status FROM hub_requests WHERE id=?", (row["task_id"],)).fetchone()
                if task is None or task["status"] not in {"planned", "in_progress"}:
                    raise OwnershipError("canonical task no longer dispatchable")
                con.execute("UPDATE coding_implementation_lease SET expires_at=? WHERE singleton=1", (time.time() + ttl,))
                def release_guarded(outcome):
                    self._history(con, row, "released", _label(outcome, "outcome", 500))
                    con.execute("DELETE FROM coding_implementation_lease WHERE singleton=1")
                yield release_guarded
                con.commit()
            except Exception:
                con.rollback()
                raise

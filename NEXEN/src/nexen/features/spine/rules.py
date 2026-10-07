"""Rules engine: no workflow, MARVIN idea or swarm job can break a rule.

Every action goes through ``check``. The verdict is allow, allow_with_approval or blocked, with every rule that
fired and a ranked list of lawful alternatives. The owner's example is built in:

  A new workflow wants Account B, B already posted its daily cap  ->  blocked(quota).
  Alternatives: wait for the next window; run on an EXISTING test account with headroom; or request a NEW test
  account (account creation is an owner step). A test account must carry original, separately made content for a
  stated experiment. Mirroring B's content, or opening accounts only to beat a cap, is refused.

Numbers in rules.json are editable at any time (``set``). Defaults marked uncalibrated are the owner's example
values, not measured platform limits; calibrate them from real platform behavior and results.
"""
import copy
import itertools
import json
import sqlite3
import threading
import time

from nexen.core import gate, paths

DEFAULT = {
    "version": 1,
    "calibration": "UNCALIBRATED: numbers are the owner's example (4 per day). Replace with measured values.",
    "platforms": {
        "tiktok": {"posts_per_day_per_account": 4, "min_gap_minutes": 90, "ai_disclosure": True, "affiliate_disclosure": True, "calibrated": False},
        "youtube": {"posts_per_day_per_account": 3, "min_gap_minutes": 180, "ai_disclosure": True, "affiliate_disclosure": True, "calibrated": False},
        "instagram": {"posts_per_day_per_account": 3, "min_gap_minutes": 120, "ai_disclosure": True, "affiliate_disclosure": True, "calibrated": False},
    },
    "accounts": [
        {"id": "A", "platform": "tiktok", "handle": "passionhomecare", "role": "main", "status": "unverified"},
        {"id": "B", "platform": "tiktok", "handle": "(owner to set)", "role": "main", "status": "unverified"},
        {"id": "E", "platform": "tiktok", "handle": "(not created)", "role": "test", "status": "not_created"},
        {"id": "YT-GAMING", "platform": "youtube", "handle": "OG Draco", "role": "main", "status": "unverified"},
        {"id": "YT-LAB", "platform": "youtube", "handle": "NEXEN Lab", "role": "test", "status": "unverified"},
        {"id": "YT-SHORTS", "platform": "youtube", "handle": "NEXEN Workflow Shorts", "role": "test", "status": "unverified"},
    ],
    "budget": {"daily_cap_usd": 0.0, "paid_requires_marvin_approval": True},
    "experiments": {"graduate_after_runs": 3, "min_lift": 0.2, "max_test_accounts_per_platform": 3, "cooldown_days": 7},
    "content": {"original_only": True, "mirror_across_accounts": False, "rotate_identities_to_evade_limits": False},
    "quiet_hours": {"start": "23:00", "end": "06:00", "applies_to": ["post"]},
    "clipping": {"requires_paid_campaign_or_research_label": True},
    "rejected_artifacts": [],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, ts REAL, account TEXT, platform TEXT, kind TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, status TEXT, runs INTEGER DEFAULT 0, baseline REAL, lift REAL, last_account TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, ts REAL, workflow TEXT, account TEXT, metric REAL, note TEXT);
"""


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class Rules:
    def __init__(self, config_path=None, db_path=None, clock=None):
        self.config_path = config_path or (paths.DATA / "rules.json")
        self.db_path = str(db_path or (paths.DATA / "rules.db"))
        self.clock = clock or time.time
        self.lock = threading.RLock()
        if self.db_path != ":memory:":
            paths.ensure_data()
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.cfg = self.load()

    # ----------------------------------------------------------------- config the owner can change any time
    def load(self):
        cfg = copy.deepcopy(DEFAULT)
        try:
            if self.config_path != ":memory:" and self.config_path.exists():
                _merge(cfg, json.loads(self.config_path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, AttributeError):
            pass
        return cfg

    def save(self):
        if self.config_path == ":memory:":
            return
        paths.ensure_data()
        self.config_path.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")

    def set(self, dotted, value):
        node = self.cfg
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node[p]
        old = node.get(parts[-1])
        node[parts[-1]] = value
        self.save()
        gate.audit("rule_changed", {"path": dotted, "old": old, "new": value})
        return {"path": dotted, "old": old, "new": value}

    def upsert_account(self, account):
        with self.lock:
            accts = [a for a in self.cfg["accounts"] if a["id"] != account["id"]]
            accts.append(account)
            self.cfg["accounts"] = accts
            self.save()

    # ----------------------------------------------------------------- usage accounting
    def _day_start(self, now):
        lt = time.localtime(now)
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

    def posts_today(self, account):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM usage WHERE account=? AND kind='post' AND ts>=?", (account, self._day_start(self.clock()))).fetchone()["c"]

    def last_post(self, account):
        with self.lock:
            r = self.db.execute("SELECT MAX(ts) t FROM usage WHERE account=? AND kind='post'", (account,)).fetchone()
        return r["t"]

    def record_use(self, account, kind="post", ref=""):
        acct = self.account(account)
        with self.lock:
            self.db.execute("INSERT INTO usage(ts,account,platform,kind,ref) VALUES(?,?,?,?,?)", (self.clock(), account, acct["platform"] if acct else "", kind, ref))
            self.db.commit()

    def account(self, ident):
        return next((a for a in self.cfg["accounts"] if a["id"] == ident), None)

    # ----------------------------------------------------------------- workflows and experiments
    def workflow(self, wid):
        with self.lock:
            r = self.db.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
        return dict(r) if r else {"id": wid, "status": "untested", "runs": 0, "baseline": None, "lift": None}

    def record_run(self, workflow, account, metric, baseline=None, note=""):
        """Log an experiment result. A workflow graduates after N runs whose mean beats the baseline by min_lift."""
        with self.lock:
            self.db.execute("INSERT INTO runs(ts,workflow,account,metric,note) VALUES(?,?,?,?,?)", (self.clock(), workflow, account, float(metric), note[:200]))
            rows = [r["metric"] for r in self.db.execute("SELECT metric FROM runs WHERE workflow=?", (workflow,))]
            mean = sum(rows) / len(rows)
            lift = (mean - baseline) / baseline if baseline else None
            ex = self.cfg["experiments"]
            status = "graduated" if (len(rows) >= ex["graduate_after_runs"] and lift is not None and lift >= ex["min_lift"]) else ("testing" if len(rows) < ex["graduate_after_runs"] else "rejected")
            self.db.execute("INSERT OR REPLACE INTO workflows(id,status,runs,baseline,lift,last_account) VALUES(?,?,?,?,?,?)", (workflow, status, len(rows), baseline, lift, account))
            self.db.commit()
        return self.workflow(workflow)

    # ----------------------------------------------------------------- the verdict
    def _quiet(self, now):
        q = self.cfg["quiet_hours"]
        lt = time.localtime(now)
        m = lt.tm_hour * 60 + lt.tm_min
        s, e = _hm(q["start"]), _hm(q["end"])
        return (m >= s or m < e) if s > e else (s <= m < e)

    def _next_window(self, account, plat):
        cfg = self.cfg["platforms"][plat]
        last = self.last_post(account)
        t = self.clock()
        if self.posts_today(account) >= cfg["posts_per_day_per_account"]:
            t = self._day_start(t) + 86400
        elif last:
            t = max(t, last + cfg["min_gap_minutes"] * 60)
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

    def check(self, action, autonomous=False, _depth=0):
        """action: {type, platform, account, workflow, content_id, mirrors, purpose, spend, campaign, research, approved, count}"""
        a = dict(action)
        kind = a.get("type", "post")
        reasons, approvals, blocks = [], [], []
        plat = a.get("platform") or (self.account(a.get("account")) or {}).get("platform")
        acct = self.account(a.get("account")) if a.get("account") else None
        now = self.clock()

        if autonomous and gate.stop_active():
            blocks.append("STOP: global STOP is active; autonomous work is paused")
        if a.get("content_id") in self.cfg.get("rejected_artifacts", []):
            blocks.append("REJECTED: the owner rejected this artifact; rework it, never recycle it")

        if kind in {"post", "publish"}:
            approvals.append("APPROVAL: public posts need the owner's exact-action approval and a provider receipt readback")
            if acct is None:
                blocks.append("ACCOUNT: no account chosen or unknown account")
            else:
                if acct["status"] == "not_created":
                    blocks.append("ACCOUNT_NOT_CREATED: %s does not exist yet; creating it is an owner step (identity, captcha)" % acct["id"])
                pcfg = self.cfg["platforms"].get(acct["platform"], {})
                cap = pcfg.get("posts_per_day_per_account", 1)
                used = self.posts_today(acct["id"]) + int(a.get("count", 1)) - 1
                if used >= cap:
                    blocks.append("QUOTA: %s has %d of %d posts today on %s (next window %s)" % (acct["id"], self.posts_today(acct["id"]), cap, acct["platform"], self._next_window(acct["id"], acct["platform"])))
                last = self.last_post(acct["id"])
                if last and (now - last) < pcfg.get("min_gap_minutes", 0) * 60:
                    blocks.append("GAP: last post on %s was under %d minutes ago" % (acct["id"], pcfg["min_gap_minutes"]))
                if self._quiet(now) and "post" in self.cfg["quiet_hours"]["applies_to"]:
                    reasons.append("QUIET_HOURS: inside quiet hours %s to %s; schedule for the next window" % (self.cfg["quiet_hours"]["start"], self.cfg["quiet_hours"]["end"]))
                    blocks.append("QUIET_HOURS: not now")
                wf = self.workflow(a["workflow"]) if a.get("workflow") else None
                if wf and wf["status"] != "graduated" and acct["role"] == "main":
                    blocks.append("UNTESTED_ON_MAIN: workflow %s is %s; main accounts only run graduated workflows" % (a["workflow"], wf["status"]))
                if wf and wf["status"] == "rejected":
                    blocks.append("WORKFLOW_REJECTED: its experiment failed the lift bar")
                if a.get("mirrors"):
                    blocks.append("MIRROR: the same content may not be copied across accounts (duplication and identity-evasion risk)")
                if not self.cfg["content"]["original_only"] is True:
                    reasons.append("CONFIG: original_only is off; owner changed it")
                if pcfg.get("ai_disclosure"):
                    reasons.append("DISCLOSE: label AI-generated content")
                if a.get("affiliate") and pcfg.get("affiliate_disclosure"):
                    reasons.append("DISCLOSE: label affiliate links")

        elif kind == "account_create":
            approvals.append("OWNER_STEP: account creation needs the owner (identity, captcha, KYC)")
            ex = self.cfg["experiments"]
            plat = a.get("platform")
            tests = [x for x in self.cfg["accounts"] if x["platform"] == plat and x["role"] == "test"]
            if a.get("purpose") != "experiment":
                blocks.append("PURPOSE: accounts are opened for a named experiment with original content, never to add volume or beat a cap")
            if not a.get("experiment_id"):
                blocks.append("EXPERIMENT: an account needs an experiment id with a hypothesis and a success metric")
            if len(tests) >= ex["max_test_accounts_per_platform"]:
                blocks.append("MAX_TEST_ACCOUNTS: %d test accounts already exist on %s" % (len(tests), plat))
            if a.get("mirrors"):
                blocks.append("MIRROR: a new account may not mirror another account's content")

        elif kind in {"spend", "ad", "purchase"}:
            amt = float(a.get("spend", 0))
            approvals.append("MARVIN_APPROVAL: paid usage needs an exact approval naming amount, purpose, provider, scope")
            if amt > self.cfg["budget"]["daily_cap_usd"] and not a.get("approved"):
                blocks.append("BUDGET: %.2f exceeds the daily cap of %.2f without an approval" % (amt, self.cfg["budget"]["daily_cap_usd"]))

        elif kind == "clip":
            if self.cfg["clipping"]["requires_paid_campaign_or_research_label"] and not (a.get("campaign") or a.get("research")):
                blocks.append("CLIP_RULE: clip only for an active paid campaign or a research run labeled do-not-post")

        elif kind in {"message", "outreach"}:
            approvals.append("APPROVAL: messages to people need the owner and a draft review")

        elif kind == "credentials":
            blocks.append("OWNER_ONLY: credentials, captcha and KYC are entered by the owner")

        if kind == "experiment":
            wf = self.workflow(a.get("workflow", ""))
            if acct is None:
                blocks.append("ACCOUNT: choose a test account")
            elif acct["role"] != "test":
                blocks.append("EXPERIMENT_ON_MAIN: experiments run on test accounts only")

        status = "blocked" if blocks else ("allow_with_approval" if approvals and not a.get("approved") else "allow")
        verdict = {"status": status, "action": kind, "account": a.get("account"), "blocks": blocks, "approvals": approvals, "notes": reasons}
        if blocks and _depth == 0 and kind in {"post", "publish", "experiment"}:
            verdict["alternatives"] = self.alternatives(a, blocks, autonomous)
        return verdict

    # ----------------------------------------------------------------- lawful alternatives, each re-checked
    def alternatives(self, a, blocks, autonomous=False):
        out = []
        text = " ".join(blocks)
        plat = a.get("platform") or (self.account(a.get("account")) or {}).get("platform")
        wf = self.workflow(a["workflow"]) if a.get("workflow") else None
        untested = bool(wf and wf["status"] in {"untested", "testing"}) or a.get("purpose") == "experiment"

        def verified(label, action, extra=""):
            v = self.check(action, autonomous, _depth=1)
            out.append({"option": label, "status": v["status"], "detail": extra or "; ".join(v["blocks"] or v["approvals"] or ["ok"])})

        if "QUOTA" in text or "GAP" in text or "QUIET_HOURS" in text:
            nxt = self._next_window(a["account"], plat) if a.get("account") and self.account(a["account"]) else "next window"
            out.append({"option": "Wait for the next window", "status": "allow_with_approval", "detail": "earliest %s on %s" % (nxt, a.get("account"))})
        if untested and "MIRROR" not in text and "REJECTED" not in text:
            tests = [x for x in self.cfg["accounts"] if x["platform"] == plat and x["role"] == "test"]
            usable = [x for x in tests if x["status"] != "not_created"]
            for t in usable:
                verified("Run the experiment on existing test account %s" % t["id"], {**a, "type": "post", "account": t["id"], "purpose": "experiment"})
            if not usable:
                if len(tests) < self.cfg["experiments"]["max_test_accounts_per_platform"] or any(x["status"] == "not_created" for x in tests):
                    nc = next((x for x in tests if x["status"] == "not_created"), None)
                    verified("Request a new test account%s for this experiment (owner creates it)" % (" " + nc["id"] if nc else ""),
                             {"type": "account_create", "platform": plat, "purpose": "experiment", "experiment_id": a.get("workflow") or "exp", "mirrors": False})
        mains = [x for x in self.cfg["accounts"] if x["platform"] == plat and x["role"] == "main" and x["id"] != a.get("account") and x["status"] != "not_created"]
        if "QUOTA" in text and not a.get("mirrors") and wf and wf["status"] == "graduated":
            for m in mains:
                verified("Post DIFFERENT content on main account %s (never a copy)" % m["id"], {**a, "account": m["id"], "mirrors": False})
        others = [p for p in self.cfg["platforms"] if p != plat]
        if others and "ACCOUNT" not in text:
            out.append({"option": "Adapt the workflow to another platform with its own cap (%s)" % ", ".join(others), "status": "allow_with_approval", "detail": "new original cut per platform"})
        if "UNTESTED_ON_MAIN" in text and not out:
            out.append({"option": "Run the workflow as an experiment first", "status": "allow_with_approval", "detail": "needs a test account"})
        return out

    # ----------------------------------------------------------------- every situation, precomputed
    def scenario_matrix(self):
        """Enumerate the situation space and store each verdict. 'Calculate all possibilities' made literal."""
        keys = ["type", "quota_hit", "graduated", "account_exists", "test_headroom", "stop", "mirror", "purpose", "approved", "quiet"]
        space = {
            "type": ["post", "experiment", "account_create", "spend", "clip", "message"],
            "quota_hit": [False, True], "graduated": [False, True], "account_exists": [True, False], "test_headroom": [True, False],
            "stop": [False, True], "mirror": [False, True], "purpose": ["experiment", "volume"], "approved": [False, True], "quiet": [False, True],
        }
        rows, classes = [], {}
        for combo in itertools.product(*[space[k] for k in keys]):
            s = dict(zip(keys, combo))
            sim = Rules(config_path=":memory:", db_path=":memory:", clock=lambda: time.mktime((2026, 10, 6, 13 if not s["quiet"] else 2, 0, 0, 0, 0, -1)))
            sim.cfg = copy.deepcopy(self.cfg)
            for acc in sim.cfg["accounts"]:
                if acc["role"] == "test":
                    acc["status"] = "unverified" if s["test_headroom"] else "not_created"
            main_id = "B"
            if not s["account_exists"]:
                sim.account(main_id)["status"] = "not_created"
            if s["quota_hit"]:
                cap = sim.cfg["platforms"]["tiktok"]["posts_per_day_per_account"]
                for i in range(cap):
                    sim.db.execute("INSERT INTO usage(ts,account,platform,kind,ref) VALUES(?,?,?,?,?)", (sim.clock() - 3 * 3600 - i * 600, main_id, "tiktok", "post", ""))
                sim.db.commit()
            sim.db.execute("INSERT OR REPLACE INTO workflows(id,status,runs) VALUES(?,?,?)", ("W1", "graduated" if s["graduated"] else "untested", 3 if s["graduated"] else 0))
            sim.db.commit()
            act = {"type": s["type"], "platform": "tiktok", "account": main_id if s["type"] != "experiment" else "E", "workflow": "W1", "mirrors": s["mirror"],
                   "purpose": s["purpose"], "approved": s["approved"], "experiment_id": "X1", "spend": 5, "research": False}
            if s["type"] == "account_create":
                act.pop("account")
            if s["stop"]:
                paths_stop = gate.paths.STOP_FILE
                autonomous = True
                stop_now = True
            else:
                autonomous, stop_now = False, False
            orig = gate.stop_active
            gate.stop_active = (lambda: stop_now)
            try:
                v = sim.check(act, autonomous=autonomous)
            finally:
                gate.stop_active = orig
            sig = v["status"] + "|" + ",".join(sorted({b.split(":")[0] for b in v["blocks"]}))
            classes[sig] = classes.get(sig, 0) + 1
            rows.append({**s, "status": v["status"], "blocks": sorted({b.split(":")[0] for b in v["blocks"]}),
                         "alternatives": [x["option"] for x in v.get("alternatives", [])][:4]})
        summary = {"situations": len(rows), "outcome_classes": dict(sorted(classes.items(), key=lambda kv: -kv[1]))}
        if self.config_path != ":memory:":
            paths.ensure_data()
            (paths.DATA / "scenario-matrix.json").write_text(json.dumps({"summary": summary, "rows": rows}), encoding="utf-8")
        return summary

    def status(self):
        today = {a["id"]: self.posts_today(a["id"]) for a in self.cfg["accounts"]}
        return {"calibration": self.cfg["calibration"], "platforms": self.cfg["platforms"], "accounts": self.cfg["accounts"], "posts_today": today,
                "experiments": self.cfg["experiments"]}

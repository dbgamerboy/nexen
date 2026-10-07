import json
import random
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import core, gate, paths  # noqa: E402
from nexen.brain import Brain  # noqa: E402
from nexen.marvin import selfcode  # noqa: E402
from nexen.marvin.agent import Agent  # noqa: E402
from nexen.marvin.traces import TraceStore, complexity  # noqa: E402
from nexen.learning.ledger import Ledger  # noqa: E402
from nexen.spine import decide as decide_mod, finetune, indicators, packs, research, workflowgen  # noqa: E402
from nexen.spine.engine import Spine  # noqa: E402
from nexen.spine.models import Models  # noqa: E402
from nexen.spine.problems import CATALOG  # noqa: E402
from nexen.spine.rules import Rules  # noqa: E402
from nexen.spine.schedule import Schedule  # noqa: E402
from nexen.spine.swap import Swap, SLOTS  # noqa: E402
from nexen.spine.world import World, lexicon_score  # noqa: E402

NOON = time.mktime((2026, 10, 6, 13, 0, 0, 0, 0, -1))


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = {k: getattr(paths, k) for k in ("DATA", "STATE_DB", "AUDIT_LOG", "STOP_FILE", "APP")}
        paths.DATA, paths.STATE_DB, paths.AUDIT_LOG = t / "data", t / "data" / "state.db", t / "data" / "audit.jsonl"
        paths.STOP_FILE, paths.APP = t / "STOP", t / "app"
        (paths.APP / "engine" / "nexen").mkdir(parents=True)
        paths.DATA.mkdir(parents=True)
        self.saved_live = indicators.live
        indicators.live = lambda timeout=10: []

    def tearDown(self):
        indicators.live = self.saved_live
        from nexen import reliability
        if reliability._spine is not None:  # release the sandboxed spine database so Windows can delete the temp folder
            reliability._spine.db.close()
            reliability._spine = None
        for k, v in self.saved.items():
            setattr(paths, k, v)
        import gc
        gc.collect()  # drop unreferenced sqlite handles so Windows can delete the temp folder
        self.tmp.cleanup()

    def brain(self):
        b = Brain(app=core.App(Ledger()), memory=True)
        b.rules.clock = lambda: NOON
        packs.AGENTS["marvin"]["stores"] = ["v4-ledger", "spine", "failures"]
        packs.AGENTS["coder"]["stores"] = ["spine", "failures", "v4-ledger"]
        return b


class SpineCatalog(Sandbox):
    def test_catalog_integrity(self):
        ids = [p["id"] for p in CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 60)
        for p in CATALOG:
            self.assertTrue(p["playbooks"][0]["steps"] and p["playbooks"][0]["verify"], p["id"])
            self.assertGreaterEqual(len(p["symptoms"]), 2, p["id"])

    def test_known_error_text_diagnosed(self):
        s = Spine(":memory:")
        d = s.diagnose("sqlite3.OperationalError: database is locked while two workers write")
        self.assertTrue(d["confident"])
        self.assertEqual(d["matches"][0]["id"], "COD-007")
        d = s.diagnose("MARVIN cannot find a model, the lookup timed out: TimeoutError 11434")
        self.assertEqual(d["matches"][0]["id"], "ENV-003")

    def test_unrelated_is_novel_not_forced(self):
        s = Spine(":memory:")
        d = s.diagnose("the purple elephant invoice portal returned a kaleidoscope")
        self.assertTrue(d["novel"])

    def test_held_out_generalization_floor(self):
        r = Spine(":memory:").evaluate()
        self.assertGreaterEqual(r["full"]["top3"], 0.80)
        self.assertGreaterEqual(r["language_only"]["top3"], 0.70)
        self.assertGreaterEqual(r["full"]["top1"], 0.55)

    def test_playbook_variants_optimize_with_outcomes(self):
        s = Spine(":memory:", rng=random.Random(1))
        s.problems["ENV-001"]["playbooks"].append({"id": "ENV-001-B", "steps": ["alt"], "verify": ["v"], "rollback": ["r"], "ext": False})
        for _ in range(12):
            s.record_outcome("ENV-001", True, "ENV-001-B")
            s.record_outcome("ENV-001", False, "ENV-001-A")
        picks = [s.pick_variant("ENV-001")["id"] for _ in range(30)]
        self.assertGreater(picks.count("ENV-001-B"), 24)

    def test_novel_candidate_promotes_after_two_clean_successes(self):
        s = Spine(":memory:")
        r = s.resolve("the purple elephant invoice portal returned a kaleidoscope")
        self.assertEqual(r["kind"], "novel")
        cid = r["candidate"]["id"]
        self.assertEqual(s.record_outcome(cid, True)["promoted_as"], None)
        out = s.record_outcome(cid, True)
        self.assertTrue(out["promoted_as"].startswith("NOV-"))
        self.assertIn(out["promoted_as"], s.problems)
        again = s.resolve("the purple elephant invoice portal returned a kaleidoscope")
        self.assertEqual(again["kind"], "known")

    def test_failed_candidate_never_promotes(self):
        s = Spine(":memory:")
        cid = s.resolve("zebra quantum widget exploded unexpectedly")["candidate"]["id"]
        s.record_outcome(cid, True)
        s.record_outcome(cid, False)
        self.assertIsNone(s.record_outcome(cid, True)["promoted_as"])

    def test_premortem_flags_gates_and_stop(self):
        s = Spine(":memory:")
        pm = s.premortem("scan the F: vault then publish a reel and buy credits")
        ids = {r["id"] for r in pm["risks"]}
        self.assertIn("ENV-001", ids)
        self.assertTrue({"POL-001", "POL-002"} <= set(pm["gates"]) | ids)
        self.assertEqual(pm["go"], "needs owner approval")
        self.assertEqual(s.premortem("start the autonomous swarm now")["go"], "blocked by STOP")

    def test_observed_failures_raise_probability(self):
        s = Spine(":memory:")
        before = s.rate("ENV-003")
        for i in range(8):
            s.db.execute("INSERT INTO occurrences(ts,problem_id,fp,source,text) VALUES('t','ENV-003',?,?,?)", ("fp%d" % i, "x", "y"))
        self.assertGreater(s.rate("ENV-003"), before)


class RulesEngine(Sandbox):
    def rules(self, hour=13):
        t = time.mktime((2026, 10, 6, hour, 0, 0, 0, 0, -1))
        return Rules(config_path=":memory:", db_path=":memory:", clock=lambda: t)

    def fill(self, r, account, n):
        for i in range(n):
            r.db.execute("INSERT INTO usage(ts,account,platform,kind,ref) VALUES(?,?,?,?,?)", (r.clock() - 6 * 3600 + i * 600, account, "tiktok", "post", ""))
        r.db.commit()

    def test_owner_example_account_b_at_cap(self):
        r = self.rules()
        self.fill(r, "B", 4)
        v = r.check({"type": "post", "platform": "tiktok", "account": "B", "workflow": "NEW"})
        self.assertEqual(v["status"], "blocked")
        self.assertTrue(any(b.startswith("QUOTA") for b in v["blocks"]))
        opts = " | ".join(a["option"] for a in v["alternatives"])
        self.assertIn("new test account", opts)
        self.assertIn("next window", opts.lower())
        self.assertNotIn("Post DIFFERENT content on main", opts)  # untested workflow may not go to a main account

    def test_graduated_workflow_may_use_other_main_with_different_content(self):
        r = self.rules()
        self.fill(r, "B", 4)
        r.db.execute("INSERT INTO workflows(id,status,runs) VALUES('W','graduated',3)")
        v = r.check({"type": "post", "platform": "tiktok", "account": "B", "workflow": "W"})
        self.assertTrue(any("DIFFERENT content on main account A" in a["option"] for a in v["alternatives"]))

    def test_mirroring_and_cap_evasion_refused(self):
        r = self.rules()
        self.assertEqual(r.check({"type": "post", "platform": "tiktok", "account": "A", "workflow": "W", "mirrors": True})["status"], "blocked")
        v = r.check({"type": "account_create", "platform": "tiktok", "purpose": "volume", "experiment_id": ""})
        self.assertEqual(v["status"], "blocked")
        self.assertTrue(any("PURPOSE" in b for b in v["blocks"]))
        ok = r.check({"type": "account_create", "platform": "tiktok", "purpose": "experiment", "experiment_id": "X1", "mirrors": False})
        self.assertEqual(ok["status"], "allow_with_approval")

    def test_experiment_only_on_test_accounts_and_graduation(self):
        r = self.rules()
        self.assertEqual(r.check({"type": "experiment", "account": "A", "workflow": "W"})["status"], "blocked")
        r.account("E")["status"] = "unverified"
        self.assertEqual(r.check({"type": "post", "platform": "tiktok", "account": "E", "workflow": "W", "purpose": "experiment"})["status"], "allow_with_approval")
        for m in (120, 130, 140):
            wf = r.record_run("W", "E", m, baseline=100)
        self.assertEqual(wf["status"], "graduated")
        r2 = self.rules()
        for m in (90, 95, 100):
            self.assertIn(r2.record_run("W2", "E", m, baseline=100)["status"], {"testing", "rejected"})
        self.assertEqual(r2.workflow("W2")["status"], "rejected")

    def test_quiet_hours_gap_spend_clip_rejected_stop(self):
        r = self.rules(hour=2)
        self.assertEqual(r.check({"type": "post", "platform": "tiktok", "account": "A", "workflow": "W"})["status"], "blocked")
        r = self.rules()
        self.assertEqual(r.check({"type": "spend", "spend": 5})["status"], "blocked")
        self.assertEqual(r.check({"type": "spend", "spend": 5, "approved": True})["status"], "allow")
        self.assertEqual(r.check({"type": "clip"})["status"], "blocked")
        self.assertEqual(r.check({"type": "clip", "research": True})["status"], "allow")
        r.cfg["rejected_artifacts"] = ["P03"]
        self.assertEqual(r.check({"type": "post", "platform": "tiktok", "account": "A", "workflow": "W", "content_id": "P03"})["status"], "blocked")
        self.assertEqual(r.check({"type": "credentials"})["status"], "blocked")
        paths.STOP_FILE.write_text("1")
        self.assertTrue(any(b.startswith("STOP") for b in r.check({"type": "clip", "research": True}, autonomous=True)["blocks"]))

    def test_config_changes_take_effect_and_are_audited(self):
        r = self.rules()
        r.set("platforms.tiktok.posts_per_day_per_account", 2)
        self.fill(r, "A", 2)
        self.assertTrue(any(b.startswith("QUOTA") for b in r.check({"type": "post", "platform": "tiktok", "account": "A", "workflow": "W"})["blocks"]))
        self.assertTrue(paths.AUDIT_LOG.exists())

    def test_scenario_matrix_covers_space_and_never_allows_a_violation(self):
        r = self.rules()
        s = r.scenario_matrix()
        self.assertGreaterEqual(s["situations"], 3000)
        rows = json.loads((paths.DATA / "scenario-matrix.json").read_text()) if (paths.DATA / "scenario-matrix.json").exists() else None
        if rows is None:
            r.config_path = paths.DATA / "rules.json"
            r.scenario_matrix()
            rows = json.loads((paths.DATA / "scenario-matrix.json").read_text())
        for row in rows["rows"]:
            if row["stop"]:
                self.assertEqual(row["status"], "blocked")
            if row["type"] == "account_create" and row["purpose"] == "volume":
                self.assertEqual(row["status"], "blocked")
            if row["type"] == "post" and row["mirror"]:
                self.assertEqual(row["status"], "blocked")
            if row["type"] == "post" and row["quota_hit"] and row["account_exists"] and row["status"] != "blocked":
                self.fail(row)


class SwapRegistry(Sandbox):
    def test_every_slot_has_candidates_and_safe_default(self):
        sw = Swap(":memory:")
        for sid in SLOTS:
            s = sw.slot(sid)
            self.assertTrue(s["active"] in s["candidates"])
        self.assertIn("base", sw.slot("adapter.marvin")["candidates"])

    def test_poor_performance_swaps_internal_slot_and_reverts(self):
        t = [1_000_000.0]
        sw = Swap(":memory:", clock=lambda: t[0])
        for _ in range(4):
            sw.record("model.chat", 0.0, ok=False)
        rec = sw.recommend("model.chat")
        self.assertTrue(rec["swap"] and rec["auto_allowed"])
        out = sw.sweep()
        self.assertEqual(out["swapped"][0]["slot"], "model.chat")
        self.assertNotEqual(sw.current("model.chat"), "strong:antigravity")
        t[0] += 10
        self.assertFalse(sw.recommend("model.chat")["swap"])  # cooldown
        sw.revert("model.chat")
        self.assertEqual(sw.current("model.chat"), "strong:antigravity")

    def test_external_slots_only_recommend(self):
        sw = Swap(":memory:")
        for _ in range(6):
            sw.record("hustle.primary", 2.0, ok=False)
        out = sw.sweep()
        self.assertFalse([x for x in out["swapped"] if x["slot"] == "hustle.primary"])
        self.assertTrue([x for x in out["recommended"] if x["slot"] == "hustle.primary"])

    def test_unknown_candidate_rejected(self):
        with self.assertRaises(ValueError):
            Swap(":memory:").apply("model.chat", "nonsense")


class ModelsAndAdapters(Sandbox):
    def test_failover_records_and_demotes(self):
        sw = Swap(":memory:")
        calls = []

        def caller(cand, prompt, system, timeout):
            calls.append(cand)
            if cand == "strong:antigravity":
                raise RuntimeError("down")
            return "ok answer"
        m = Models(sw, caller)
        r = m.consult("hello", "model.chat")
        self.assertTrue(r["ok"])
        self.assertEqual(r["candidate"], "strong:claude")
        self.assertEqual(calls[:2], ["strong:antigravity", "strong:claude"])
        for _ in range(3):
            m.consult("hello", "model.chat")
        self.assertEqual(sw.health("model.chat")["state"], "poor")  # antigravity kept failing
        sw.sweep()
        self.assertEqual(sw.current("model.chat"), "strong:claude")  # the sweep demoted it
        self.assertEqual(sw.health("model.chat")["state"], "ok")

    def test_all_fail_reports_errors(self):
        m = Models(Swap(":memory:"), lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
        r = m.consult("hi", "model.chat")
        self.assertFalse(r["ok"])
        self.assertTrue(r["errors"])

    def test_adapter_slot_maps_to_registered_tag_only(self):
        from nexen.spine import models as mm
        sw = Swap(":memory:")
        m = Models(sw)
        self.assertIsNone(m.adapter_tag("marvin"))
        mm.register_adapter("lora:marvin-v4-spine", "marvin-v4:latest", "qwen3-4b", 0.7)
        sw.apply("adapter.marvin", "lora:marvin-v4-spine")
        self.assertEqual(m.adapter_tag("marvin"), "marvin-v4:latest")
        sw.revert("adapter.marvin")
        self.assertIsNone(m.adapter_tag("marvin"))

    def test_secrets_redacted_from_model_output(self):
        m = Models(Swap(":memory:"), lambda *a: "here is sk-abcdefghijklmnop1234 ok")
        self.assertNotIn("abcdefghijklmnop1234", m.consult("x", "model.chat")["text"])


class WorldModel(Sandbox):
    def fake_get(self, url, timeout=12):
        if "gdeltproject" in url:
            return json.dumps({"timeline": [{"series": "Average Tone", "data": [{"date": "d%d" % i, "value": -2.0 + i * 0.1} for i in range(20)]}]})
        if "hn.algolia" in url:
            return json.dumps({"hits": [{"title": "t", "points": 10 * i, "num_comments": i} for i in range(1, 11)]})
        if "wikimedia" in url:
            return json.dumps({"items": [{"articles": [{"article": "Main_Page", "views": 9}, {"article": "Some_Topic", "views": 8}]}]})
        if "mastodon" in url:
            return json.dumps([{"name": "tag1"}, {"name": "tag2"}])
        return "<rss><channel><item><title>Markets surge on record growth</title></item><item><title>War fears and crisis deepen</title></item></channel></rss>"

    def test_collect_summary_labels_and_missing(self):
        w = World(":memory:", get=self.fake_get, sleep=lambda s: None)
        r = w.collect(["tiktok"], gdelt_gap=0)
        self.assertEqual(r["missing"], [])
        s = w.summary(["tiktok"])
        row = s["topics"][0]
        self.assertAlmostEqual(row["media_tone"], -1.05, places=2)
        self.assertGreater(row["tone_trend"], 0)
        self.assertEqual(row["hn_stories"], 10)
        self.assertIn("Some Topic", s["wikipedia_top"])
        self.assertNotIn("Main Page", s["wikipedia_top"])
        self.assertTrue(any("not what people think" in g for g in s["reading_guide"]))
        self.assertEqual(len(s["feeds"]), 4)

    def test_rate_limit_and_failures_are_reported_never_fabricated(self):
        def bad(url, timeout=12):
            raise urllib.error.HTTPError(url, 429, "Too Many", {}, None)
        w = World(":memory:", get=bad, sleep=lambda s: None)
        r = w.collect(["tiktok"], gdelt_gap=0)
        self.assertEqual(r["answered"], 0)
        self.assertTrue(r["missing"])
        self.assertEqual(w.summary(["tiktok"])["topics"], [])

    def test_facts_supersede_instead_of_piling_up(self):
        w = World(":memory:", get=self.fake_get, sleep=lambda s: None)
        w.collect(["tiktok"], sources=["gdelt"], gdelt_gap=0)
        from nexen.learning.novel import NovelLearner
        nl = NovelLearner(Ledger())
        for f in w.facts():
            self.assertEqual(nl.ingest(f)["op"], "ADD")
        w.get = lambda url, timeout=12: json.dumps({"timeline": [{"data": [{"value": 1.5}] * 10}]})
        w.collect(["tiktok"], sources=["gdelt"], gdelt_gap=0)
        ops = [nl.ingest({**f, "observed_at": "2099-01-01T12:00:00"})["op"] for f in w.facts()]
        self.assertIn("UPDATE", ops)

    def test_lexicon(self):
        self.assertGreater(lexicon_score("record growth and success"), 0)
        self.assertLess(lexicon_score("crisis war crash"), 0)


class PromptAssembly(Sandbox):
    def test_every_prompt_carries_packs_risks_rules_and_a_receipt(self):
        b = self.brain()
        b.app.novel.ingest({"text": "The baseline ffmpeg clipper crops vertical clips and burns captions from whisper transcripts.", "source_ids": ["file:a#1@1"]})
        p = b.packs.prompt("clipper", "clip a video and publish it to tiktok")
        self.assertIn("Standing rules", p["prompt"])
        self.assertIn("TASK: clip a video", p["prompt"])
        self.assertIn("premortem", p["prompt"])
        rc = p["receipt"]
        self.assertEqual(rc["agent"], "clipper")
        self.assertIn("spine", rc["stores_asked"])
        self.assertTrue(b.packs.receipts(1)[0]["hash"] == p["hash"])

    def test_dead_store_is_reported_not_silent(self):
        b = self.brain()
        res = b.stores.fanout("anything", ["v4-ledger", "qdrant"], k=2)
        self.assertIn("qdrant", res["unavailable"])
        self.assertIn("ok", res["status"]["v4-ledger"])

    def test_every_agent_has_a_pack_and_adapter_or_base(self):
        b = self.brain()
        for name in packs.AGENTS:
            self.assertTrue(b.packs.brief(name)["chars"] > 100, name)

    def test_prompt_never_contains_secrets(self):
        b = self.brain()
        p = b.packs.prompt("marvin", "my token is sk-abcdefghijklmnop1234 please use it")
        self.assertNotIn("abcdefghijklmnop1234", p["prompt"])


class Decisions(Sandbox):
    def test_deterministic_decision_names_sources_and_gates(self):
        b = self.brain()
        paths.STOP_FILE.write_text("1")
        d = decide_mod.decide(b, "database is locked while two workers write the ledger")
        self.assertEqual(d["kind"], "known")
        self.assertFalse(d["model_consulted"])
        self.assertIn("no model consulted", d["model_note"])
        self.assertTrue(d["evidence"] or d["recommendation"])
        d2 = decide_mod.decide(b, "publish a reel to tiktok and buy credits for ads")
        self.assertTrue(d2["gates"])
        self.assertIn("owner", d2["next_action"].lower())

    def test_decision_with_rules_action_blocks(self):
        b = self.brain()
        for i in range(4):
            b.rules.db.execute("INSERT INTO usage(ts,account,platform,kind,ref) VALUES(?,?,?,?,?)", (NOON - 6 * 3600 + i * 600, "B", "tiktok", "post", ""))
        b.rules.db.commit()
        d = decide_mod.decide(b, "post the new workflow clip", action={"type": "post", "platform": "tiktok", "account": "B", "workflow": "NEW"})
        self.assertTrue(any(g.startswith("rules: blocked") for g in d["gates"]))

    def test_consult_uses_model_and_survives_outage(self):
        b = self.brain()
        b.models.caller = lambda cand, prompt, system, timeout: "Decision: do the safe thing."
        d = decide_mod.decide(b, "database is locked while two workers write", consult=True)
        self.assertTrue(d["model_consulted"])
        b.models.caller = lambda *a: (_ for _ in ()).throw(RuntimeError("all down"))
        d = decide_mod.decide(b, "database is locked while two workers write", consult=True)
        self.assertFalse(d["model_consulted"])
        self.assertTrue(d["recommendation"])


class Routine(Sandbox):
    def test_money_first_order_and_due_and_adjust(self):
        s = Schedule(path=":memory:", clock=lambda: time.mktime((2026, 10, 6, 7, 10, 0, 0, 0, -1)))
        p = s.plan()
        self.assertEqual(p["priority_order"][0], "survival")
        self.assertLess(p["priority_order"].index("services"), p["priority_order"].index("music"))
        self.assertEqual([b["id"] for b in s.due()], ["stability"])
        s.move("stability", "09:00", 30)
        self.assertEqual(s.due(), [])
        s.pause_lane("services")
        self.assertTrue([b for b in s.plan()["blocks"] if b["id"] == "services"][0]["paused"])
        s.add("extra", "15:00", 20, "services", "extra block")
        with self.assertRaises(ValueError):
            s.add("extra2", "15:00", 20, "nope", "bad lane")
        s.set_weight("music", 11)
        self.assertEqual(s.plan()["priority_order"][0], "music")

    def test_stop_and_gaming_annotate_blocks(self):
        s = Schedule(path=":memory:", clock=lambda: time.mktime((2026, 10, 6, 22, 30, 0, 0, 0, -1)))
        paths.STOP_FILE.write_text("1")
        s.set_gaming(True)
        due = s.due()
        self.assertEqual(due[0]["id"], "training")
        self.assertEqual(len(due[0]["blocked_by"]), 2)

    def test_default_week_has_no_conflicts_and_markdown_renders(self):
        s = Schedule(path=":memory:")
        self.assertEqual(s.conflicts(), [])
        self.assertIn("Priority:", s.render_markdown())

    def test_overnight_block_wraps_midnight(self):
        s = Schedule(path=":memory:", clock=lambda: time.mktime((2026, 10, 6, 3, 0, 0, 0, 0, -1)))
        self.assertEqual([b["id"] for b in s.due()], ["quiet"])


class WorkflowsUnderRules(Sandbox):
    def test_draft_inactive_and_rewritten_when_it_would_break_a_rule(self):
        r = Rules(config_path=":memory:", db_path=":memory:", clock=lambda: NOON)
        for i in range(4):
            r.db.execute("INSERT INTO usage(ts,account,platform,kind,ref) VALUES(?,?,?,?,?)", (NOON - 6 * 3600 + i * 600, "A", "tiktok", "post", ""))
        r.db.commit()
        plan = workflowgen.draft("New TikTok shop product clip workflow from the research note", ["url:youtube:abc"], r, account="A")
        self.assertEqual(plan["status"], "draft-rewritten-by-rules")
        self.assertIn("test account", plan["rewritten_as"].lower())
        self.assertTrue(plan["gates"])
        self.assertEqual(workflowgen.list_drafts()[0]["status"], "draft-rewritten-by-rules")
        self.assertNotIn("active", plan["status"].replace("inactive", ""))

    def test_spend_creates_a_gate(self):
        r = Rules(config_path=":memory:", db_path=":memory:", clock=lambda: NOON)
        plan = workflowgen.draft("Upwork proposal automation service", ["file:x"], r, platform="youtube", spend=20)
        self.assertEqual(plan["spend_verdict"]["status"], "blocked")


class MarvinCoreLayer(Sandbox):
    def test_complexity_tiers(self):
        self.assertEqual(complexity("hi")["tier"], "trivial")
        self.assertIn(complexity("First analyze the code ```def f(): pass```, then explain why it fails and compare two fixes. 1. cause 2. fix 3. test. Write the patch?")["tier"], {"complex", "very_complex"})

    def test_legacy_traces_not_mined_or_discovered_without_evidence(self):
        b = self.brain()
        for i in range(4):
            b.traces.record("coder", "fix database locked sqlite ledger error number %d" % i, "Use mode=ro and a timeout.", "local:qwen2.5-coder:7b", True, 2.0, 0.9)
        b.traces.record("coder", "fix the port conflict", "ignored", "strong:claude", False, 90.0, 0.0)
        a = b.traces.analyze(min_n=1)
        self.assertEqual(a["unverified_traces"], 5)
        self.assertEqual(a["models"], {})
        self.assertEqual(len(b.traces.mine()["sft"]), 0)
        self.assertEqual(len(b.traces.mine()["failure"]), 0)
        found = b.orchestrator.discover_skills(min_successes=3)
        self.assertEqual(found, [])

    def test_orchestrator_cycle_gate_and_no_training_started(self):
        b = self.brain()
        paths.STOP_FILE.write_text("1")
        r = b.orchestrator.run()
        self.assertIn("STOP", r["note"])
        self.assertNotIn("recursive", r["steps"])
        self.assertFalse(r["steps"]["train_ready"])
        self.assertTrue(r["accepted"])

    def test_agent_deterministic_without_model_and_learns(self):
        b = self.brain()
        b.models.caller = lambda *a: (_ for _ in ()).throw(RuntimeError("no model"))
        out = b.agent("coder").run("sqlite database is locked while two workers write", use_model=True)
        self.assertTrue(out["deterministic"])
        self.assertIn("COD-007", out["answer"])
        self.assertGreaterEqual(len(b.traces.rows()), 1)

    def test_agent_tool_loop_and_gate(self):
        b = self.brain()
        script = iter(['{"tool": "diagnose", "args": {"text": "database is locked"}}', '{"final": "Use the COD-007 playbook."}'])
        b.models.caller = lambda cand, prompt, system, timeout: next(script)
        out = b.agent("coder").run("why is the database locked")
        self.assertEqual(out["answer"], "Use the COD-007 playbook.")
        self.assertEqual(out["steps"][0]["tool"], "diagnose")
        self.assertFalse(out["deterministic"])

    def test_ticket_packet_schema(self):
        b = self.brain()
        r = b.agent("swarm").ticket("Build one real handler", ["engine/x.py"], [])
        packet = json.loads(Path(r["packet"]).read_text())
        for k in ("packet_version", "objective", "file_ownership", "acceptance_checks", "resource_budget", "stop_conditions", "result_contract"):
            self.assertIn(k, packet)
        self.assertEqual(packet["resource_budget"]["max_external_spend"], 0)
        self.assertIn("not dispatched", r["status"])

    def test_selfcode_screens_and_applies_only_through_tested_path(self):
        self.assertTrue(selfcode.screen([{"path": "../evil.py", "content": "x=1"}]))
        self.assertTrue(selfcode.screen([{"path": "engine/a.py", "content": "import os\nos.system('dir')"}]))
        self.assertTrue(selfcode.screen([{"path": "engine/a.py", "content": "def broken(:"}]))
        self.assertTrue(selfcode.screen([{"path": "tests/test_x.py", "content": "x=1"}]))
        self.assertFalse(selfcode.screen([{"path": "engine/nexen/ok.py", "content": "VALUE = 1\n"}]))
        b = self.brain()
        reply = json.dumps({"files": [{"path": "engine/nexen/ok.py", "content": "VALUE = 2\n"}], "notes": "bump"})
        b.models.caller = lambda *a: reply
        out = selfcode.propose(b, "bump value")
        self.assertEqual(out["status"], "prepared")
        paths.STOP_FILE.write_text("1")
        out2 = selfcode.propose(b, "bump value", auto=True)
        self.assertIn("STOP", out2["status"])
        paths.STOP_FILE.unlink()
        out3 = selfcode.propose(b, "bump value again", auto=True)
        self.assertEqual(out3["status"], "applied", out3)
        self.assertEqual((paths.APP / "engine" / "nexen" / "ok.py").read_text(), "VALUE = 2\n")
        bad = json.dumps({"files": [{"path": "engine/nexen/ok.py", "content": "import os\nos.system('x')"}]})
        b.models.caller = lambda *a: bad
        self.assertEqual(selfcode.propose(b, "evil", auto=True)["stage"], "screen")


class TrainingShardAndResearch(Sandbox):
    def test_shard_has_train_dpo_and_held_out_eval_without_overlap(self):
        m = finetune.export(Spine(":memory:"))
        self.assertGreater(m["files"]["spine_sft.jsonl"]["rows"], 150)
        self.assertGreater(m["files"]["spine_dpo.jsonl"]["rows"], 100)
        self.assertGreater(m["files"]["spine_eval.jsonl"]["rows"], 20)
        def rows(name):
            return [json.loads(l) for l in Path(m["files"][name]["path"]).read_text(encoding="utf-8").splitlines()]
        train = {r["messages"][1]["content"] for r in rows("spine_sft.jsonl")}
        for r in rows("spine_eval.jsonl"):
            self.assertNotIn(r["messages"][1]["content"], train)
        for row in rows("spine_dpo.jsonl"):
            self.assertTrue(row["chosen"] and row["rejected"] and row["rejected_is"])

    def test_research_items_have_clickable_source_links(self):
        b = self.brain()
        b.app.novel.ingest({"text": "OpenJarvis mines traces into training pairs and accepts a tuned model only if the eval improves.", "title": "YouTube: talk", "source_ids": ["url:youtube:abc123"], "origin": "youtube"})
        items = research.items(b.app, "traces", origin="youtube")
        self.assertEqual(items[0]["sources"][0]["link"], "https://www.youtube.com/watch?v=abc123")
        self.assertIsNone(research.link_for("chat:codex:x"))

    def test_vtt_parsing_dedupes_rolling_captions(self):
        p = Path(self.tmp.name) / "a.vtt"
        p.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello there\n\n00:00:02.000 --> 00:00:04.000\nhello there\nthis is a test\n", encoding="utf-8")
        self.assertEqual(research._vtt_text(p), "hello there this is a test")


if __name__ == "__main__":
    unittest.main()

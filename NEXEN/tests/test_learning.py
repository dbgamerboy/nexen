import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import textsim  # noqa: E402
from nexen.learning.golden import run_golden  # noqa: E402
from nexen.learning.ledger import Ledger  # noqa: E402
from nexen.learning.meta import SelfTuner  # noqa: E402
from nexen.learning.novel import NovelLearner, source_trust  # noqa: E402
from nexen.learning.recursive import LocalCorpusProvider, RecursiveLearner  # noqa: E402

SRC = "file:/a.md#x@1"
SRC2 = "file:/b.md#y@2"


class TextSim(unittest.TestCase):
    def test_exact_and_unrelated(self):
        self.assertEqual(textsim.composite("Hello world again", "hello   WORLD again"), 1.0)
        self.assertLess(textsim.composite("clipping pipeline ffmpeg captions", "tiktok shop affiliate payout rules"), 0.2)

    def test_paraphrase_scores_between(self):
        s = textsim.composite("n8n runs locally on port 5678 with one active workflow",
                              "local n8n on port 5678 has one workflow active")
        self.assertGreater(s, 0.45)

    def test_negation_and_numbers(self):
        self.assertTrue(textsim.has_negation("it does not work"))
        self.assertFalse(textsim.has_negation("it works"))
        self.assertEqual(textsim.numbers("38 workflows, 1,000 runs"), {"38", "1000"})

    def test_paragraphs_keep_heading(self):
        doc = "# Title\n\n" + ("alpha beta gamma delta " * 6) + "\n\n## Next\n\n" + ("epsilon zeta eta theta " * 6)
        ps = textsim.paragraphs(doc)
        self.assertEqual([h for h, _ in ps], ["Title", "Next"])


class NovelGate(unittest.TestCase):
    def test_golden_wall_passes_with_defaults(self):
        passed, total, failures = run_golden()
        self.assertEqual(failures, [])
        self.assertEqual(passed, total)

    def test_supersede_keeps_history_and_as_of_recall(self):
        nl = NovelLearner(Ledger())
        a = nl.ingest({"text": "Local n8n holds 29 workflows and one active health schedule.", "source_ids": [SRC],
                       "observed_at": "2026-09-25T10:00:00"})
        self.assertEqual(a["op"], "ADD")
        b = nl.ingest({"text": "Local n8n holds 38 workflows and one active health schedule.", "source_ids": [SRC2],
                       "observed_at": "2026-09-26T10:00:00"})
        self.assertEqual(b["op"], "UPDATE")
        old = nl.ledger.get(a["item_id"])
        self.assertEqual(old["status"], "superseded")
        self.assertIsNotNone(old["valid_to"])
        now_hits = nl.recall("how many n8n workflows", k=3)
        self.assertIn("38", now_hits[0]["text"])
        self.assertEqual([h["id"] for h in now_hits if h["id"] == a["item_id"]], [])

    def test_reinforce_raises_trust_and_evidence(self):
        nl = NovelLearner(Ledger())
        text = "The Ollama server listens on port 11434 and serves local models."
        a = nl.ingest({"text": text, "source_ids": ["chat:x"]})
        before = nl.ledger.get(a["item_id"])["trust"]
        nl.ingest({"text": text, "source_ids": ["receipt:y"]})
        after = nl.ledger.get(a["item_id"])
        self.assertEqual(after["evidence_n"], 2)
        self.assertGreater(after["trust"], before)

    def test_held_item_can_be_released_after_provenance(self):
        nl = NovelLearner(Ledger())
        r = nl.ingest({"text": "Fiverr gig drafts need requirements gallery and a publish click from the owner."})
        self.assertEqual(r["op"], "HOLD")
        self.assertEqual(nl.ledger.get(r["item_id"])["status"], "held")
        nl.ledger.db.execute("UPDATE items SET source_ids=? WHERE id=?", ('["owner:direct"]', r["item_id"]))
        out = nl.release(r["item_id"])
        self.assertTrue(out["ok"], out)

    def test_never_publishes(self):
        nl = NovelLearner(Ledger())
        r = nl.ingest({"text": "Curviana denim pilot needs a product truth sheet before any script.", "source_ids": [SRC]})
        self.assertFalse(r["can_publish"])

    def test_source_trust_diminishing(self):
        one = source_trust(["file:a"])
        two = source_trust(["file:a", "url:b"])
        self.assertGreater(two, one)
        self.assertLess(two, 1.0)
        self.assertEqual(source_trust([]), 0.0)

    def test_gaps_favor_money_and_archive_cells(self):
        nl = NovelLearner(Ledger())
        nl.ingest({"text": "Ollama listens on port 11434 for local model inference requests.", "source_ids": [SRC]})
        gaps = nl.gaps()
        self.assertEqual(gaps[0]["domain"], "money")
        self.assertTrue(nl.archive())

    def test_bad_input_types(self):
        nl = NovelLearner(Ledger())
        self.assertEqual(nl.ingest("")["op"], "REJECT")
        self.assertEqual(nl.ingest({"text": None})["op"], "REJECT")
        self.assertEqual(nl.ingest({"text": "x" * 50000, "source_ids": [SRC]})["can_publish"], False)


class Recursive(unittest.TestCase):
    def make_corpus(self, tmp):
        (Path(tmp) / "a.md").write_text(
            "# Clipping\n\nThe baseline ffmpeg clipper crops clips to vertical nine sixteen format and burns captions "
            "from whisper small transcripts before quality control review.\n\n"
            "# Campaigns\n\nWhop campaign clips need an active paid campaign before posting and quality control review "
            "of captions is required by the brief.\n", encoding="utf-8")
        (Path(tmp) / "b.md").write_text(
            "# Quality\n\nQuality control review of clipper output checks caption timing, crop framing and audio "
            "loudness before any clip leaves the research folder.\n", encoding="utf-8")

    def test_run_admits_and_descends_with_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_corpus(tmp)
            rl = RecursiveLearner(NovelLearner(Ledger()), LocalCorpusProvider([tmp]))
            res = rl.run(questions=["clipper captions ffmpeg"], strategy="deep", max_seconds=10)
            self.assertGreaterEqual(res["ops"].get("ADD", 0), 1)
            self.assertLessEqual(res["max_depth"], 3)
            self.assertFalse(res["automatic_publish"])
            self.assertGreaterEqual(rl.ledger.stats()["lessons"], 1)
            self.assertGreaterEqual(len(rl.ledger.skills()), 1)
            before = rl.ledger.count()
            res2 = rl.run(questions=["clipper captions ffmpeg"], strategy="deep", max_seconds=10)
            self.assertEqual(rl.ledger.count(), before)  # second pass learns nothing new
            self.assertEqual(res2["ops"].get("ADD", 0), 0)

    def test_candidate_cap_and_provider_error(self):
        class Boom:
            def fetch(self, q, n):
                raise RuntimeError("down")
        rl = RecursiveLearner(NovelLearner(Ledger()), Boom())
        res = rl.run(questions=["anything at all"], strategy="wide")
        self.assertEqual(res["evaluated"], 0)

        class Flood:
            def fetch(self, q, n):
                return [{"text": "unique statement number %d about topic%d with detail words" % (i, i), "source_ids": [SRC]} for i in range(n)]
        rl2 = RecursiveLearner(NovelLearner(Ledger()), Flood())
        res2 = rl2.run(questions=["flood topic"], strategy="wide", max_candidates=5)
        self.assertLessEqual(res2["evaluated"], 5)

    def test_ucb_tries_every_strategy_first(self):
        rl = RecursiveLearner(NovelLearner(Ledger()), None)
        seen = set()
        for _ in range(3):
            s = rl.choose_strategy()
            seen.add(s)
            rl.ledger.strategy_update(s, 0.5)
        self.assertEqual(seen, {"wide", "balanced", "deep"})

    def test_tree_mode_cycle_and_depth(self):
        rl = RecursiveLearner(NovelLearner(Ledger()), None)
        seeds = [{"candidate_id": "a", "text": "Postiz is installed locally with zero connected channels today.", "source_ids": [SRC]}]

        def expand(c):
            return [{"candidate_id": "a", "text": c["text"], "source_ids": [SRC]},
                    {"candidate_id": "b", "text": "Cloudflare pages signup awaits the owner sign in before any deploy.", "source_ids": [SRC]}]
        out = rl.run_tree(seeds, expand=expand, max_depth=3)
        self.assertLessEqual(out["summary"]["evaluated"], 50)
        self.assertTrue(any(c["status"] == "excluded_cycle_or_duplicate" for c in out["candidates"]))
        with self.assertRaises(ValueError):
            rl.run_tree(seeds, max_depth=4)


class Tuner(unittest.TestCase):
    def test_no_labels_no_change(self):
        led = Ledger()
        before = led.params()
        rep = SelfTuner(led).tune()
        self.assertIsNotNone(rep["skipped"])
        self.assertEqual(led.params(), before)

    def test_tune_changes_within_bounds_and_rolls_back(self):
        led = Ledger()
        # owner keeps rejecting medium-novelty admits: the tuner should raise novelty_min
        for i in range(20):
            novelty = 0.36 + (i % 4) * 0.01
            led.log_decision("x%d" % i, "ADD", novelty, 0.30, 0.6, 0.5)
            led.label_decision("x%d" % i, 0, "owner")
        for i in range(10):
            led.log_decision("g%d" % i, "ADD", 0.9, 0.05, 0.7, 0.6)
            led.label_decision("g%d" % i, 1, "owner")
        before = led.params()["novelty_min"]
        rep = SelfTuner(led).tune()
        after = led.params()["novelty_min"]
        self.assertGreater(after, before, rep)
        self.assertLessEqual(after, 0.60)
        self.assertEqual(run_golden(led.params())[0], run_golden()[1])
        undone = SelfTuner(led).rollback()
        self.assertTrue(undone)
        self.assertAlmostEqual(led.params()["novelty_min"], before, places=6)


if __name__ == "__main__":
    unittest.main()

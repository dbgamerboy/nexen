import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_spine import Sandbox  # noqa: E402
from nexen.learning import headstart  # noqa: E402
from nexen.spine import forecast  # noqa: E402


class Forecasts(Sandbox):
    def tearDown(self):
        for c in forecast._conn.values():
            c.close()
        forecast._conn.clear()
        super().tearDown()

    def test_ten_thousand_unique_bounded_forecasts(self):
        b = self.brain()
        out = forecast.generate(b.spine)
        self.assertGreaterEqual(out["generated"], 10000)
        rows = forecast.build(b.spine)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(all(0.01 <= r["probability"] <= 0.95 and r["status"] == "predicted" for r in rows))
        self.assertEqual(forecast.stats(b.spine)["forecasts"], out["generated"])

    def test_regeneration_is_idempotent_and_leaves_observed_rates_alone(self):
        b = self.brain()
        before = {pid: b.spine.rate(pid) for pid in b.spine.problems}
        forecast.generate(b.spine)
        forecast.generate(b.spine)
        self.assertEqual(forecast.stats(b.spine)["forecasts"], len(forecast.build(b.spine)))
        self.assertEqual(before, {pid: b.spine.rate(pid) for pid in b.spine.problems})

    def test_lookup_returns_matching_class_ranked_by_expected_loss(self):
        b = self.brain()
        forecast.generate(b.spine)
        hits = forecast.lookup(b.spine, "python was not found, opens the Microsoft Store", k=5)
        self.assertTrue(hits and all(h["problem_id"] == "ENV-002" for h in hits[:1]))
        loss = [h["probability"] * h["impact"] for h in hits]
        self.assertEqual(loss, sorted(loss, reverse=True))

    def test_lookup_of_nonsense_returns_empty(self):
        b = self.brain()
        forecast.generate(b.spine)
        self.assertEqual(forecast.lookup(b.spine, "zzqx vvkp wwnn", k=3), [])


class Distill(unittest.TestCase):
    SRC_QA = {"id": "x/qa", "kind": "qa", "q": "question", "a": "answer"}

    def test_qa_row_without_a_failure_is_dropped(self):
        self.assertIsNone(headstart.distill(self.SRC_QA, {"question": "How do I sort a list in Python please", "answer": "Use sorted()."}, 1))

    def test_qa_row_with_error_becomes_symptom_and_fix(self):
        d = headstart.distill(self.SRC_QA, {"question": "My script raises a KeyError when the config is missing, how do I fix it?", "answer": "Use dict.get with a default. Then test it."}, 3)
        self.assertIn("Symptom:", d["text"])
        self.assertIn("Fix: Use dict.get with a default.", d["text"])
        self.assertTrue(d["source_ids"][0].startswith("url:huggingface.co/datasets/x/qa"))

    def test_swe_row_names_exceptions_and_keeps_instance_id(self):
        d = headstart.distill({"id": "p/swe", "kind": "swe"}, {"repo": "a/b", "instance_id": "a__b-1", "problem_statement": "Crash on load.\nTraceback: ValueError raised in parse()"}, 1)
        self.assertIn("ValueError", d["text"])
        self.assertTrue(d["source_ids"][0].endswith("#a__b-1"))

    def test_bad_row_types_do_not_crash(self):
        self.assertIsNone(headstart.distill(self.SRC_QA, {"question": None, "answer": None}, 1))
        self.assertIsNone(headstart.distill({"id": "z", "kind": "unknown"}, {}, 1))


if __name__ == "__main__":
    unittest.main()


class CliJson(unittest.TestCase):
    def test_cmd_exe_stripped_quotes_and_file_args(self):
        import tempfile
        from nexen.cli_spine import _loads
        self.assertEqual(_loads('{type:post,platform:tiktok,account:B}'), {"type": "post", "platform": "tiktok", "account": "B"})
        self.assertEqual(_loads("{'a': 1, 'ok': true}"), {"a": 1, "ok": True})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write('{"x": 2}')
        self.assertEqual(_loads("@" + f.name), {"x": 2})
        with self.assertRaises(ValueError):
            _loads("not json at all")

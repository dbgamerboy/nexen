import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen.learning.ledger import Ledger  # noqa: E402
from nexen.learning.novel import NovelLearner  # noqa: E402


class ExtensionKeepsBoth(unittest.TestCase):
    def test_extension_never_deletes_older_item(self):
        nl = NovelLearner(Ledger())
        a = nl.ingest({"text": "The baseline clipper crops clips to vertical nine sixteen and burns captions from whisper transcripts.", "source_ids": ["file:a#1@1"]})
        b = nl.ingest({"text": "The baseline clipper crops clips to vertical nine sixteen, burns captions from whisper transcripts, and runs a quality control "
                               "review that checks caption timing, crop framing and loudness before export.", "source_ids": ["file:b#1@2"]})
        self.assertEqual(a["op"], "ADD")
        self.assertEqual(b["op"], "ADD", b)
        self.assertEqual(nl.ledger.get(a["item_id"])["status"], "admitted")
        self.assertEqual(nl.ledger.get(b["item_id"])["status"], "admitted")
        self.assertEqual(nl.ledger.count(), 2)


class SupersessionRegression(unittest.TestCase):
    """Found on the first real-data run: template passages with a changed number were superseding each other."""

    def test_bakeoff_winners_and_inventory_rows_both_kept(self):
        nl = NovelLearner(Ledger())
        pairs = [
            ("**Winner on this input: smart-captions.** One input is one data point; run 3+ different videos before switching the default clipper. Score 0.91 on 131s.",
             "**Winner on this input: business-operations.** One input is one data point; run 3+ different videos before switching the default clipper. Score 0.84 on 152s."),
            ("0114. baseline_clipper.py [SOURCE / OLD BUTTON] H:\\NEXEN\\clipping\\baseline_clipper.py SOURCE not a separate app",
             "0115. campaign_clip.py [SOURCE / OLD BUTTON] H:\\NEXEN\\clipping\\campaign_clip.py SOURCE not a separate app"),
        ]
        for a, b in pairs:
            ra = nl.ingest({"text": a, "source_ids": ["file:r1#1@a"]})
            rb = nl.ingest({"text": b, "source_ids": ["file:r2#1@b"]})
            self.assertNotEqual(rb["op"], "UPDATE", rb["reasons"])
            self.assertEqual(nl.ledger.get(ra["item_id"])["status"], "admitted")

    def test_true_value_change_still_supersedes(self):
        nl = NovelLearner(Ledger())
        nl.ingest({"text": "Local n8n holds 29 workflows and one active health schedule.", "source_ids": ["file:a#1@1"], "observed_at": "2026-09-25T10:00:00"})
        r = nl.ingest({"text": "Local n8n holds 38 workflows and one active health schedule.", "source_ids": ["file:b#1@2"], "observed_at": "2026-09-26T10:00:00"})
        self.assertEqual(r["op"], "UPDATE")

    def test_reaudit_undoes_unjustified_supersession(self):
        nl = NovelLearner(Ledger())
        a = nl.ingest({"text": "Winner on this input is smart captions with score 0.91 on the first video.", "source_ids": ["file:a#1@1"]})
        # simulate the old buggy rule: force a supersession between two different facts
        b = nl.ingest({"text": "Dropshipping pilot Curviana needs a verified supplier and product truth sheet before any script.", "source_ids": ["file:b#1@2"]})
        with nl.ledger.lock:
            nl.ledger.db.execute("UPDATE items SET supersedes=? WHERE id=?", (a["item_id"], b["item_id"]))
            nl.ledger.db.commit()
        nl.ledger.supersede(a["item_id"])
        out = nl.reaudit_supersessions()
        self.assertEqual(out["undone"], 1)
        self.assertEqual(nl.ledger.get(a["item_id"])["status"], "admitted")

    def test_undo_restores_older_item(self):
        nl = NovelLearner(Ledger())
        a = nl.ingest({"text": "Local n8n holds 29 workflows and one active health schedule.", "source_ids": ["file:a#1@1"], "observed_at": "2026-09-25T10:00:00"})
        b = nl.ingest({"text": "Local n8n holds 38 workflows and one active health schedule.", "source_ids": ["file:b#1@2"], "observed_at": "2026-09-26T10:00:00"})
        out = nl.undo_supersede(b["item_id"])
        self.assertTrue(out["ok"])
        self.assertEqual(nl.ledger.get(a["item_id"])["status"], "admitted")
        self.assertIsNone(nl.ledger.get(a["item_id"])["valid_to"])
        self.assertFalse(nl.undo_supersede(a["item_id"])["ok"])


if __name__ == "__main__":
    unittest.main()

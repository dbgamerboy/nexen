import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import identity  # noqa: E402
from nexen.learning.ledger import Ledger  # noqa: E402
from nexen.learning.novel import NovelLearner  # noqa: E402
from nexen.spine.engine import Spine  # noqa: E402


class JarvisIsMarvin(unittest.TestCase):
    def test_normalize_rewrites_the_assistant_name(self):
        self.assertEqual(identity.normalize("Ask JARVIS to run it."), "Ask MARVIN to run it.")
        self.assertEqual(identity.normalize("jarvis said hi, Jarvis agreed, J.A.R.V.I.S. waited"), "marvin said hi, Marvin agreed, MARVIN waited")
        self.assertEqual(identity.normalize("nothing here"), "nothing here")
        self.assertEqual(identity.normalize(None), None)

    def test_protected_names_stay(self):
        for keep in ("OpenJarvis mines traces", "see isair/jarvis license", "ethanplusai/jarvis", "Arnav3241__Jarvis-v13", "jarvis_runtime.py", "route /jarvis",
                     "open-jarvis__OpenJarvis", "JARVIS-AI-Assistant"):
            self.assertEqual(identity.normalize(keep), keep, keep)
        self.assertEqual(identity.normalize("JARVIS uses OpenJarvis ideas"), "MARVIN uses OpenJarvis ideas")

    def test_agent_alias(self):
        for a in ("jarvis", "JARVIS", "Jarvis", "J.A.R.V.I.S", "jarvis ai", None, "marvin"):
            self.assertEqual(identity.agent_key(a), "marvin")
        self.assertEqual(identity.agent_key("coder"), "coder")

    def test_ledger_never_stores_two_names(self):
        nl = NovelLearner(Ledger())
        r = nl.ingest({"text": "JARVIS routes the daily plan through the schedule and the rules engine before anything runs.", "title": "JARVIS routine", "source_ids": ["file:x#1@1"]})
        item = nl.ledger.get(r["item_id"])
        self.assertIn("MARVIN", item["text"])
        self.assertNotIn("JARVIS", item["text"] + item["title"])

    def test_assembled_prompt_never_says_jarvis_and_persona_is_coherent(self):
        from nexen.spine import packs
        for k, a in packs.AGENTS.items():
            self.assertNotIn("jarvis", a["persona"].lower(), k)
        self.assertNotIn("earlier name", packs.AGENTS["marvin"]["persona"].replace("only ever had this one name", ""))

    def test_spine_resolves_name_confusion(self):
        d = Spine(":memory:").diagnose("is JARVIS a different assistant from MARVIN")
        self.assertEqual(d["matches"][0]["id"], "NAM-001")


if __name__ == "__main__":
    unittest.main()

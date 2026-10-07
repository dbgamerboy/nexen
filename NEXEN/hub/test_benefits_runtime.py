import json
import shutil
import unittest
import uuid
from pathlib import Path

from benefits_runtime import Benefits, ProfileUpdate, ResourceUpdate
from test_support import fixture_root, load_core_definitions


class BenefitsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_root() / ("benefits-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        core = load_core_definitions()
        self.db = core.DB(str(self.root / "benefits.sqlite3"))
        resources = {"resources": [
            {"id":"rent","name":"Rent Help","category":"housing","scope":"test","priority":1,
             "url":"https://example.test/rent","phone":"555-0100","email":"help@example.test",
             "tags":["rent","disability"],"fit":"test","action":"call","submission":"human_review"},
            {"id":"car","name":"Car Help","category":"transportation","scope":"test","priority":2,
             "url":"https://example.test/car","phone":"","email":"","tags":["no-car"],
             "fit":"test","action":"apply","submission":"human_attestation"}
        ]}
        profile = {"eligibility_flags":{"housing_risk":True,"disability_materially_limits_work":True,
                  "no_vehicle":True},"unknowns":["income"],
                  "disclosure_policy":"minimum necessary"}
        self.resources = self.root / "resources.json"
        self.profile = self.root / "profile.json"
        self.resources.write_text(json.dumps(resources), encoding="utf-8")
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        self.benefits = Benefits(self.db, self.resources, self.profile)
    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_listing_matches_and_defaults_ready(self):
        result = self.benefits.listing()
        self.assertEqual(len(result["resources"]), 2)
        self.assertEqual(result["resources"][0]["id"], "rent")
        self.assertEqual(result["resources"][0]["stage"], "ready")
        self.assertGreaterEqual(result["resources"][0]["match_count"], 1)
        self.assertFalse(result["execution"]["calls_placed"])

    def test_update_persists_kanban_state(self):
        body = ResourceUpdate(stage="waiting", notes="left voicemail",
                              next_followup="2026-10-01", last_contact="voicemail")
        row = self.benefits.update("rent", body)
        self.assertEqual(row["stage"], "waiting")
        self.assertEqual(row["notes"], "left voicemail")
        again = self.benefits.get("rent")
        self.assertEqual(again["next_followup"], "2026-10-01")

    def test_profile_update_saves_only_screening_facts(self):
        body = ProfileUpdate(city="Test City", county="Test County", zip_code="00000",
                             household_size=1, gross_monthly_income=900,
                             current_benefits="program active", housing_balance=100,
                             housing_notice_stage="notice", driver_license="yes",
                             can_insure_vehicle="unknown", business_registered="yes",
                             business_tax_years=1, cat_spay_needed=True, tax_issue_active=True)
        saved = self.benefits.update_profile(body)
        self.assertEqual(saved["facts"]["household_size"], 1)
        self.assertEqual(saved["location"]["zip_code"], "00000")
        self.assertNotIn("diagnosis", json.dumps(saved).lower())
        self.assertNotIn("household size", saved["unknowns"])

    def test_drafts_are_review_only_and_minimum_necessary(self):
        call = self.benefits.draft("rent", "call")
        self.assertIn("preserve stable housing", call["draft"])
        self.assertIn("long-term disability", call["draft"])
        self.assertNotIn("diagnos", call["draft"].lower())
        email = self.benefits.draft("rent", "email")
        self.assertEqual(email["to"], "help@example.test")
        self.assertIn("Do not attach SSN", email["warning"])


if __name__ == "__main__":
    unittest.main()

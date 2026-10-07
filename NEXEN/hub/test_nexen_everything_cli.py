"""Safety tests for central CLI integrations that read other NEXEN registries."""
import contextlib
import io
import json
import unittest

import nexen_everything


class ClippingStatusTests(unittest.TestCase):
    def test_summary_is_aggregate_only_and_never_authorizes_or_starts_actions(self):
        private_row = {
            "kind": "campaign", "id": "Private Campaign Name", "allowed": True,
            "reason": "private reason", "url": "https://private.example/campaign",
            "out_dir": r"H:\private\clips",
        }
        rows = [
            private_row,
            {"kind": "campaign", "id": "held", "allowed": False, "reason": "not paid"},
            {"kind": "client_job", "id": "job", "allowed": True},
            {"kind": "client_job", "id": "held-job", "allowed": False},
        ]
        result = nexen_everything.clipping_status(lambda: rows)
        rendered = json.dumps(result)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["campaigns"], {"total": 2, "eligible": 1, "held": 1})
        self.assertEqual(result["client_jobs"], {"total": 2, "eligible": 1, "held": 1})
        self.assertNotIn("Private Campaign Name", rendered)
        self.assertNotIn("private.example", rendered)
        self.assertNotIn("H:\\private", rendered)
        self.assertNotIn("not paid", rendered)
        self.assertFalse(any(result["actions_taken"].values()))

    def test_unavailable_and_invalid_rows_fail_closed_without_leaking_errors(self):
        unavailable = nexen_everything.clipping_status(
            lambda: (_ for _ in ()).throw(OSError(r"H:\private\campaigns.json is locked"))
        )
        invalid = nexen_everything.clipping_status(lambda: ["not a row"])

        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["unavailable_sources"], ["clip_gate"])
        self.assertNotIn("campaigns.json", json.dumps(unavailable))
        self.assertEqual(invalid["status"], "unavailable")
        self.assertEqual(invalid["invalid_rows"], 1)

    def test_canonical_cli_emits_the_same_safe_summary(self):
        output = io.StringIO()
        result = nexen_everything.main(
            ["clipping", "status"],
            clip_status_reader=lambda: [{
                "kind": "campaign", "id": "secret", "allowed": False,
                "reason": "private details",
            }],
            stdout=output,
            stderr=io.StringIO(),
        )
        payload = json.loads(output.getvalue())

        self.assertEqual(result, 0)
        self.assertEqual(payload["campaigns"], {"total": 1, "eligible": 0, "held": 1})
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("private details", output.getvalue())
        self.assertFalse(any(payload["actions_taken"].values()))

    def test_clipping_cli_rejects_non_status_commands(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                nexen_everything.main(["clipping", "run"])


class MarvinCapabilityStatusTests(unittest.TestCase):
    @staticmethod
    def descriptor():
        return {
            "internet": {"available": True, "tool": "fetch", "policy": "public HTTPS"},
            "model_install": {"available": True, "max_parameters": 7_000_000_000,
                              "quantizations": ["Q4_0", "Q4_K_M"]},
            "resident_processes_added": 0,
            "cloud_spend_enabled": False,
            "kill_switch": r"H:\private\capabilities\STOP",
            "boundary": "private internal detail",
        }

    def test_static_capabilities_are_sanitized_and_read_only(self):
        result = nexen_everything.marvin_capability_status(
            lambda: (self.descriptor(), False)
        )
        rendered = json.dumps(result)

        self.assertEqual(result["status"], "available")
        self.assertTrue(result["capabilities"]["bounded_public_https_text_fetch"])
        self.assertEqual(result["capabilities"]["model_install_max_parameters"], 7_000_000_000)
        self.assertFalse(result["capabilities"]["cloud_spend_enabled"])
        self.assertNotIn("H:\\private", rendered)
        self.assertNotIn("kill_switch", rendered)
        self.assertNotIn("private internal detail", rendered)
        self.assertFalse(any(result["actions_taken"].values()))

    def test_scoped_stop_is_reported_without_removal(self):
        result = nexen_everything.marvin_capability_status(
            lambda: (self.descriptor(), True)
        )

        self.assertEqual(result["status"], "paused")
        self.assertTrue(result["stop_active"])
        self.assertFalse(any(result["actions_taken"].values()))

    def test_missing_or_malformed_adapter_fails_closed(self):
        unavailable = nexen_everything.marvin_capability_status(
            lambda: (_ for _ in ()).throw(OSError(r"H:\private\capabilities.py missing"))
        )
        malformed = nexen_everything.marvin_capability_status(
            lambda: ({"internet": [], "model_install": {}}, False)
        )

        self.assertEqual(unavailable["status"], "unavailable")
        self.assertNotIn("capabilities.py", json.dumps(unavailable))
        self.assertTrue(unavailable["stop_active"])
        self.assertEqual(malformed["status"], "unavailable")
        self.assertTrue(malformed["stop_active"])

    def test_cli_only_accepts_capabilities_for_marvin(self):
        output = io.StringIO()
        result = nexen_everything.main(
            ["marvin", "capabilities"],
            marvin_status_reader=lambda: (self.descriptor(), False),
            stdout=output,
            stderr=io.StringIO(),
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "available")
        for rejected in (["marvin", "fetch"], ["marvin", "stop"], ["marvin", "model-install"]):
            with self.subTest(rejected=rejected), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    nexen_everything.main(rejected)


if __name__ == "__main__":
    unittest.main()

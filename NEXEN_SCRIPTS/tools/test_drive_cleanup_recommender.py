import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drive_cleanup_recommender import recommend_file, scan_drive, write_reports


class DriveCleanupRecommenderTests(unittest.TestCase):
    def test_duplicate_name_requires_verification_and_estimates_zero(self):
        result = recommend_file("Downloads/video (1).mp4", 8_000_000, 1, 2_000_000_000)
        self.assertEqual(result["category"], "possible_duplicate_copy")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("content-hash", result["next_step"])

    def test_cache_is_never_marked_auto_delete(self):
        result = recommend_file("CACHE_JUNK_REVIEW/05_AI_TMP/model.cache", 1000, 1, 2_000_000_000)
        self.assertEqual(result["category"], "cache_or_temp_review")
        self.assertNotIn("delete", result["next_step"].lower())

    def test_recovered_files_are_protected_for_review(self):
        result = recommend_file("found.000/dir0000.chk", 500, 1, 2_000_000_000)
        self.assertEqual(result["priority"], "protect")

    def test_old_backups_require_a_separate_restore_check(self):
        result = recommend_file("Backups/WindowsBackup.rar", 80 * 1024**3, 1, 2_000_000_000)
        self.assertEqual(result["category"], "old_backup_archive_review")
        self.assertIn("separate restore copy", result["next_step"])

    def test_scan_includes_hidden_files_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "drive"
            root.mkdir()
            (root / ".hidden.bin").write_bytes(b"hidden")
            child = root / "folder"
            child.mkdir()
            (child / "large.iso").write_bytes(b"x" * 64)
            outside = Path(temp) / "outside.txt"
            outside.write_text("outside")
            link = root / "linked"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            report = scan_drive(root, max_depth=None, max_seconds=None, top_n=10, progress_every=0)
            self.assertEqual(report["counts"]["files"], 2)
            self.assertEqual(report["counts"]["skipped_symlinks"], 1)
            self.assertTrue(report["scan_complete"])
            self.assertEqual(report["file_contents_read"], 0)
            self.assertEqual(report["deletions_performed"], 0)

    def test_depth_and_file_limits_mark_sizes_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "drive"
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "top.bin").write_bytes(b"123")
            (root / "a" / "b" / "deep.bin").write_bytes(b"12345")
            report = scan_drive(root, max_depth=1, max_seconds=None, top_n=10, progress_every=0)
            self.assertFalse(report["scan_complete"])
            self.assertEqual(report["counts"]["files"], 1)
            report = scan_drive(root, max_depth=None, max_seconds=None, max_files=1, top_n=10, progress_every=0)
            self.assertFalse(report["scan_complete"])

    def test_unreadable_directory_forces_partial_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "drive"
            blocked = root / "blocked"
            blocked.mkdir(parents=True)
            original = os.scandir
            calls = []
            def deny_selected(path):
                calls.append(str(path))
                if Path(path).name.casefold() == "blocked":
                    raise PermissionError("fixture")
                return original(path)
            with patch("drive_cleanup_recommender.os.scandir", side_effect=deny_selected):
                report = scan_drive(root, max_depth=None, max_seconds=None, top_n=10, progress_every=0)
            self.assertFalse(report["scan_complete"])
            self.assertGreater(report["counts"]["errors"], 0)
            self.assertTrue(any(Path(path).name.casefold() == "blocked" for path in calls))

    def test_report_inside_scan_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "drive"
            root.mkdir()
            report = scan_drive(root, max_depth=None, max_seconds=None, top_n=10, progress_every=0)
            with self.assertRaisesRegex(ValueError, "outside_scanned_drive"):
                write_reports(report, root / "reports")
            outputs = write_reports(report, Path(temp) / "reports")
            self.assertTrue((Path(temp) / "reports" / "report.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)

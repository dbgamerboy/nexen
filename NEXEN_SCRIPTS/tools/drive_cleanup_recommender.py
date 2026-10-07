"""Read-only disk inventory and review recommendations; this tool never deletes files."""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRECTORY_NAMES = {"system volume information"}
PARTIAL_SUFFIXES = {".crdownload", ".part", ".partial", ".tmp", ".download"}
PACKAGE_SUFFIXES = {".exe", ".msi", ".iso", ".zip", ".7z", ".rar", ".cab", ".dmg"}
COPY_STEM = re.compile(r"(?:\s\(\d+\)|\s+-\s*copy(?:\s*\(\d+\))?|^copy of\s+.+)$", re.I)


def _human_size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if amount < 1024 or unit == "PB":
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} PB"


def _age_days(mtime: float, now: float) -> int:
    return max(0, int((now - mtime) / 86400))


def recommend_file(relative_path: str, size: int, mtime: float, now: float) -> dict | None:
    """Return cautious next steps. No category means age/name alone is not enough."""
    path = Path(relative_path)
    parts = [part.casefold() for part in path.parts]
    name = path.name
    suffix = path.suffix.casefold()
    age = _age_days(mtime, now)
    if any(part == "found.000" or part.startswith("found.") for part in parts):
        return {"category": "recovered_data_review", "priority": "protect", "confidence": "low",
                "next_step": "Inspect recovered files and confirm any needed recovery before considering removal."}
    if any(part in {"$recycle.bin", "recycler"} for part in parts):
        return {"category": "recycle_bin_review", "priority": "review", "confidence": "medium",
                "next_step": "Review the original file names and restore anything needed before emptying this drive's Recycle Bin."}
    if any(part in {"cache", "caches", "tmp", "temp", "cache_junk_review", "05_ai_tmp"} for part in parts):
        return {"category": "cache_or_temp_review", "priority": "review", "confidence": "medium",
                "next_step": "Close the related app, confirm these are reproducible cache/temp files, then remove only selected items."}
    backup_path = any("backup" in part or "reinstall_dump" in part for part in parts)
    if backup_path and size >= 5 * 1024**3 and age >= 180:
        return {"category": "old_backup_archive_review", "priority": "review", "confidence": "low",
                "next_step": "Verify this backup opens, its files exist elsewhere, and a separate restore copy works before considering removal."}
    if suffix in PARTIAL_SUFFIXES and age >= 7:
        return {"category": "stale_partial_download_review", "priority": "review", "confidence": "medium",
                "next_step": "Confirm the download is abandoned and not resumable before removing it."}
    stem = path.stem
    base_stem = COPY_STEM.sub("", stem).strip()
    is_copy_name = base_stem != stem and bool(base_stem)
    if is_copy_name:
        return {"category": "possible_duplicate_copy", "priority": "verify_first", "confidence": "low",
                "next_step": "Compare with the unsuffixed/original file; only treat this as reclaimable after a content-hash match and backup check."}
    in_downloads = any(part in {"download", "downloads", "youtube downloads", "yoututbe downlaods"} for part in parts)
    in_installer_folder = any("installer" in part or part in {"setup", "setups"} for part in parts)
    if suffix in PACKAGE_SUFFIXES and size >= 250 * 1024 * 1024 and (in_downloads or in_installer_folder) and age >= 30:
        return {"category": "old_installer_or_archive_review", "priority": "review", "confidence": "low",
                "next_step": "Check whether the installer/archive is needed and can be downloaded again before removing it."}
    if size >= 50 * 1024**3:
        return {"category": "very_large_file_review", "priority": "review", "confidence": "low",
                "next_step": "Check ownership, backup status, and whether this can be archived or moved; age alone is not a deletion reason."}
    if in_downloads and size >= 2 * 1024**3 and age >= 180:
        return {"category": "old_large_download_review", "priority": "review", "confidence": "low",
                "next_step": "Open/preview it and confirm it is replaceable or backed up before removing it."}
    return None


def _push_largest(heap: list, limit: int, size: int, sequence: int, row: dict) -> None:
    entry = (size, sequence, row)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
    elif size > heap[0][0]:
        heapq.heapreplace(heap, entry)


def scan_drive(root: str | Path, *, max_depth: int | None = 3, max_seconds: float | None = 180,
               max_files: int | None = None, top_n: int = 100, progress_every: int = 2500) -> dict:
    """Inventory metadata only. A limited scan reports observed sizes as lower bounds."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("scan_root_must_be_a_directory")
    if max_depth is not None and max_depth < 1:
        raise ValueError("max_depth_must_be_positive_or_none")
    if max_seconds is not None and max_seconds <= 0:
        raise ValueError("max_seconds_must_be_positive_or_none")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files_must_be_positive_or_none")
    if top_n < 1:
        raise ValueError("top_n_must_be_positive")

    started = time.monotonic()
    now = time.time()
    usage = shutil.disk_usage(root)
    deadline = started + max_seconds if max_seconds is not None else None
    stack = [(root, 0)]
    dir_bytes: dict[str, int] = {}
    largest_files: list = []
    recommendations: list = []
    sequence = 0
    scanned_files = scanned_dirs = errors = skipped_links = 0
    incomplete = False
    error_samples = []
    candidate_count = 0
    observed_bytes = 0

    def hit_limit() -> bool:
        return ((deadline is not None and time.monotonic() >= deadline)
                or (max_files is not None and scanned_files >= max_files))

    while stack:
        if hit_limit():
            incomplete = True
            break
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if hit_limit():
                        incomplete = True
                        break
                    try:
                        if entry.is_symlink():
                            skipped_links += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() in SKIP_DIRECTORY_NAMES:
                                continue
                            next_depth = depth + 1
                            if max_depth is None or next_depth <= max_depth:
                                stack.append((Path(entry.path), next_depth))
                            else:
                                # The folder itself was seen, but its contents were not.
                                incomplete = True
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        size = int(info.st_size)
                        scanned_files += 1
                        observed_bytes += size
                        sequence += 1
                        relative = Path(entry.path).relative_to(root).as_posix()
                        age = _age_days(info.st_mtime, now)
                        row = {"path": str(Path(entry.path)), "relative_path": relative,
                               "size_bytes": size, "size_human": _human_size(size),
                               "modified_utc": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                               "age_days": age}
                        _push_largest(largest_files, top_n, size, sequence, row)
                        parts = Path(relative).parts
                        if parts:
                            dir_bytes[parts[0]] = dir_bytes.get(parts[0], 0) + size
                        if len(parts) > 1:
                            second = "/".join(parts[:2])
                            dir_bytes[second] = dir_bytes.get(second, 0) + size
                        suggestion = recommend_file(relative, size, info.st_mtime, now)
                        if suggestion:
                            candidate_count += 1
                            recommendation = {**row, **suggestion,
                                "bytes_if_confirmed": size if suggestion["category"] in {
                                    "cache_or_temp_review", "stale_partial_download_review",
                                    "old_installer_or_archive_review", "old_large_download_review",
                                    "very_large_file_review", "recycle_bin_review"} else 0}
                            _push_largest(recommendations, top_n, size, sequence, recommendation)
                    except OSError as exc:
                        errors += 1
                        incomplete = True
                        if len(error_samples) < 25:
                            error_samples.append({"path": entry.path, "error": type(exc).__name__})
                scanned_dirs += 1
        except OSError as exc:
            errors += 1
            incomplete = True
            if len(error_samples) < 25:
                error_samples.append({"path": str(directory), "error": type(exc).__name__})
        if progress_every and scanned_dirs and scanned_dirs % progress_every == 0:
            print(json.dumps({"progress": "scanning", "directories": scanned_dirs,
                              "files": scanned_files, "elapsed_seconds": round(time.monotonic() - started, 1)}),
                  flush=True)

    elapsed = round(time.monotonic() - started, 2)
    directory_rows = [{"relative_path": key, "observed_bytes": value,
                       "observed_size_human": _human_size(value)}
                      for key, value in dir_bytes.items()]
    directory_rows.sort(key=lambda row: row["observed_bytes"], reverse=True)
    largest_rows = [entry[2] for entry in sorted(largest_files, reverse=True)]
    recommendation_rows = [entry[2] for entry in sorted(recommendations, reverse=True)]
    return {
        "schema_version": 1,
        "tool": "drive_cleanup_recommender",
        "scan_root": str(root),
        "drive_space": {"total_bytes": usage.total, "total_human": _human_size(usage.total),
                        "used_bytes": usage.used, "used_human": _human_size(usage.used),
                        "free_bytes": usage.free, "free_human": _human_size(usage.free)},
        "scan_started_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "scan_seconds": elapsed,
        "mode": "metadata_only_read_only",
        "file_contents_read": 0,
        "deletions_performed": 0,
        "size_measurement": "logical file lengths; sparse files and hard links may reduce actual reclaimed space",
        "scan_complete": not incomplete and not stack,
        "size_note": "Observed sizes are lower bounds unless scan_complete is true.",
        "limits": {"max_depth": max_depth, "max_seconds": max_seconds, "max_files": max_files},
        "counts": {"files": scanned_files, "directories": scanned_dirs, "errors": errors,
                   "skipped_symlinks": skipped_links, "recommendation_candidates_seen": candidate_count},
        "observed_file_bytes": observed_bytes,
        "observed_file_bytes_human": _human_size(observed_bytes),
        "largest_files": largest_rows,
        "largest_directories": directory_rows[:top_n],
        "recommendations": recommendation_rows,
        "errors_sample": error_samples,
    }


def _ensure_report_outside_scan(report_dir: Path, root: Path) -> None:
    report = report_dir.resolve(strict=False)
    scan = root.resolve(strict=True)
    try:
        common = Path(os.path.commonpath([str(report), str(scan)]))
    except ValueError:
        return
    if str(common).casefold() == str(scan).casefold():
        raise ValueError("report_directory_must_be_outside_scanned_drive")


def write_reports(report: dict, output_dir: str | Path) -> list[str]:
    out = Path(output_dir)
    root = Path(report["scan_root"])
    _ensure_report_outside_scan(out, root)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "scan-summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = [("largest-files.csv", report["largest_files"]),
             ("largest-directories.csv", report["largest_directories"]),
             ("recommendations.csv", report["recommendations"])]
    outputs = [str(summary_path)]
    for filename, rows in files:
        path = out / filename
        headers = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            if headers:
                writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            else:
                path.write_text("", encoding="utf-8-sig")
        outputs.append(str(path))
    report_path = out / "report.md"
    count = report["counts"]
    status = "COMPLETE" if report["scan_complete"] else "PARTIAL — all observed sizes are lower bounds"
    lines = [
        f"# F: drive cleanup review ({status})", "",
        f"- Scan: `{report['scan_started_utc']}`; metadata only; {report['scan_seconds']} seconds.",
        f"- Space: {report['drive_space']['used_human']} used of {report['drive_space']['total_human']}; {report['drive_space']['free_human']} free.",
        f"- Inspected {count['files']:,} files in {count['directories']:,} directories; {count['errors']} access errors.",
        f"- Observed file sizes total {report['observed_file_bytes_human']}; this is not a drive total for a partial scan.",
        "- File sizes are logical lengths. Sparse files and hard links can make real reclaimed space smaller.",
        "- File contents read: 0. Files deleted: 0.", "",
        "## Largest observed directories", "",
        "| Observed size | Directory |", "|---:|---|",
    ]
    for row in report["largest_directories"][:15]:
        lines.append(f"| {row['observed_size_human']} | `{row['relative_path'].replace('|', r'\\|')}` |")
    lines.extend(["", "## Largest review candidates", "",
                  "Review each path manually. Names, age, and size do not prove a file is safe to remove.", "",
                  "| Size | Category | Confidence | Age (days) | Path | Next check |",
                  "|---:|---|---|---:|---|---|"])
    for row in report["recommendations"][:25]:
        path = row["relative_path"].replace("|", r"\|")
        next_step = row["next_step"].replace("|", r"\|")
        lines.append(f"| {row['size_human']} | {row['category']} | {row['confidence']} | {row['age_days']} | `{path}` | {next_step} |")
    lines.extend(["", "Possible duplicate names are not confirmed duplicates; the tool does not hash file contents.",
                  "Recovered files and backup archives require a working, separate restore copy before removal.",
                  "No delete operation is implemented.", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    outputs.append(str(report_path))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only F: drive cleanup recommendations; never deletes files.")
    parser.add_argument("--root", type=Path, default=Path("F:/"), help="Drive/folder to inventory (default F:/)")
    parser.add_argument("--output", type=Path,
                        default=Path(r"H:\NEXEN\reports\f-drive-cleanup"),
                        help="Report folder; must be outside the scanned drive")
    parser.add_argument("--max-depth", type=int, default=3, help="Folder levels to scan (default: 3; use 0 for full depth)")
    parser.add_argument("--max-seconds", type=float, default=180, help="Stop after this many seconds; use 0 for no time limit")
    parser.add_argument("--max-files", type=int, default=0, help="Stop after this many files; 0 means unlimited")
    parser.add_argument("--top", type=int, default=100, help="Rows kept in each report (default: 100)")
    args = parser.parse_args(argv)
    try:
        depth = None if args.max_depth == 0 else args.max_depth
        seconds = None if args.max_seconds == 0 else args.max_seconds
        files = None if args.max_files == 0 else args.max_files
        report = scan_drive(args.root, max_depth=depth, max_seconds=seconds, max_files=files, top_n=args.top)
        outputs = write_reports(report, args.output)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "partial" if not report["scan_complete"] else "complete",
                      "scan_root": report["scan_root"], "counts": report["counts"],
                      "largest_files": len(report["largest_files"]),
                      "recommendations": len(report["recommendations"]),
                      "deletions_performed": 0, "reports": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

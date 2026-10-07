# F: drive cleanup recommender

This is a read-only Python inventory tool. It reads file and directory metadata only; it does not open file contents, hash files, or delete anything. Reports are written to H: by default, never into the scanned drive.

Run a bounded scan from PowerShell:

~~~powershell
& 'H:\NEXEN_RUNTIME\python-recovery\Scripts\python.exe' 'H:\NEXEN\tools\drive_cleanup_recommender.py' --root 'F:\' --output 'H:\NEXEN\reports\f-drive-cleanup' --max-depth 3 --max-seconds 180 --max-files 250000
~~~

Open report.md first. The CSV files contain the largest observed files, largest observed directories, and review candidates. scan-summary.json records scan limits, errors, drive free space, and whether the scan was complete. A partial scan reports only lower bounds; rerun with a larger file/time limit to cover more of the drive.

The recommendations are prompts for manual review. A filename like (1) does not prove a duplicate; this tool does not compare hashes. Backup archives need a separate working restore copy. File ages and sizes do not establish that a file is disposable. Actual reclaimed space can be less than logical file sizes when files are sparse or hard-linked.

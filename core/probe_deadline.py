"""Bounded repro for expensive SQLite execution through SharedMemory.readonly.

The parent subprocess timeout is test containment, not a production fix.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
SQL = '''WITH RECURSIVE counter(n) AS (
    VALUES(0) UNION ALL SELECT n + 1 FROM counter WHERE n < 1000000000
) SELECT sum(n) FROM counter'''


def child(path):
    import memory_bridge as memory
    memory.READ_TIMEOUT_SECONDS = 0.05
    memory.CONTEXT_READ_TIMEOUT_SECONDS = 0.05
    started = time.monotonic()
    try:
        with memory.readonly(path, max_seconds=memory.CONTEXT_READ_TIMEOUT_SECONDS) as connection:
            connection.execute(SQL).fetchone()
    except sqlite3.OperationalError as error:
        print(json.dumps({'result': type(error).__name__,
                          'seconds': round(time.monotonic() - started, 3)}))
        return 0 if type(error).__name__ == 'ReadDeadlineExceeded' else 2
    print(json.dumps({'result': 'unexpected_completion'}))
    return 3


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        return child(sys.argv[2])
    with tempfile.TemporaryDirectory(dir=ROOT, prefix='fixture-') as folder:
        path = Path(folder) / 'index.sqlite3'
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE marker(id INTEGER)')
        connection.close()
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                     '--child', str(path)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=0.8)
        except subprocess.TimeoutExpired:
            print('FAIL: a 0.05-second SQLite busy timeout did not stop the expensive read within 0.8 seconds.')
            return 1
        print(result.stdout.strip())
        if result.stderr:
            print(result.stderr.strip())
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())

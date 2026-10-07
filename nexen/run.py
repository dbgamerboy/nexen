"""Entry point: python run.py <command>. Also launched by nexen.cmd and NEXEN.exe."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("NEXEN_APP", HERE)
sys.path.insert(0, os.path.join(HERE, "engine"))

from nexen.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

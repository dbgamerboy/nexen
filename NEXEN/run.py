"""Entry point: python run.py <command>."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("NEXEN_APP", HERE)
sys.path.insert(0, os.path.join(HERE, "src"))

from nexen.app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

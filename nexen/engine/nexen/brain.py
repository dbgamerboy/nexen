"""One object that wires every V4 intelligence piece together, so nothing is optional and nothing is bypassed."""
import os
import threading
import time

from . import core, identity, paths
from .marvin.agent import Agent
from .marvin.orchestrator import Orchestrator
from .marvin.traces import TraceStore
from .spine import indicators
from .spine.embed import Embedder
from .spine.engine import Spine
from .spine.models import Models
from .spine.packs import Packs
from .spine.rules import Rules
from .spine.schedule import Schedule
from .spine.stores import Stores
from .spine.swap import Swap
from .spine.world import World

_brain = None
_lock = threading.Lock()


class Brain:
    def __init__(self, app=None, memory=False, embed=None):
        self.app = app or core.get_app()
        mem = ":memory:" if memory else None
        self.spine = Spine(db_path=mem, ledger=self.app.ledger)
        self.rules = Rules(config_path=":memory:" if memory else None, db_path=mem)
        self.swap = Swap(db_path=mem)
        self.world = World(db_path=mem)
        self.embedder = Embedder(db_path=mem) if (embed or os.environ.get("NEXEN_EMBED") == "1") else None
        self.models = Models(self.swap)
        self.stores = Stores(self.app, self.spine, self.world, self.embedder)
        self._live = (0.0, [])
        self.packs = Packs(self.app, self.spine, self.rules, self.swap, self.stores, self.models, self.live_indicators, self.embedder)
        self.traces = TraceStore(db_path=mem)
        self.schedule = Schedule(self.app, path=":memory:" if memory else None)
        self.orchestrator = Orchestrator(self.app, self)
        self.agents = {}

    def live_indicators(self, ttl=60):
        t, data = self._live
        if time.time() - t > ttl:
            data = indicators.live(timeout=10)
            self._live = (time.time(), data)
        return data

    def agent(self, name="marvin"):
        name = identity.agent_key(name)
        if name not in self.agents:
            self.agents[name] = Agent(self, name)
        return self.agents[name]


def get_brain():
    global _brain
    with _lock:
        if _brain is None:
            paths.ensure_data()
            _brain = Brain()
        return _brain


def set_brain(b):
    global _brain
    _brain = b

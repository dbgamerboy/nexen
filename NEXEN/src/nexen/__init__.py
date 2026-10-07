"""NEXEN: one app that tracks, learns and connects every NEXEN piece.

V4 reads V3 and the F: legacy lines through read-only adapters.
V4 writes only under its own data folder.
"""
VERSION = "4.0.0"
LINE = "V4"


# ---- compatibility: old flat module names resolve to the new folders -------------------
import importlib as _il, importlib.abc as _abc, importlib.util as _iu, sys as _sys
_ALIAS = {"actions": "features.operations.actions", "updater": "features.operations.updater", "modbridge": "features.modules.modbridge", "api_spine": "app.api_spine", "cli": "app.cli", "cli_spine": "app.cli_spine", "server": "app.server", "mcp_server": "app.mcp_server", "autonomy": "features.learning.autonomy", "brain": "features.marvin.brain", "gate": "core.gate", "paths": "core.paths", "identity": "core.identity", "registry": "core.registry", "reliability": "core.reliability", "textsim": "shared.utils.textsim"}
_PKGS = {"connectors": "features.connectors", "learning": "features.learning", "marvin": "features.marvin", "spine": "features.spine"}

class _Alias(_abc.MetaPathFinder, _abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("nexen."):
            return None
        rel = fullname[len("nexen."):]
        head, _, rest = rel.partition(".")
        if rel in _ALIAS:
            tgt = _ALIAS[rel]
        elif head in _ALIAS and rest:
            tgt = _ALIAS[head] + "." + rest
        elif head in _PKGS:
            tgt = _PKGS[head] + ("." + rest if rest else "")
        else:
            return None
        self._target = "nexen." + tgt
        return _iu.spec_from_loader(fullname, self)
    def create_module(self, spec):
        rel = spec.name[len("nexen."):]
        head, _, rest = rel.partition(".")
        tgt = _ALIAS.get(rel) or (_ALIAS[head] + "." + rest if head in _ALIAS and rest else None) or (_PKGS[head] + ("." + rest if rest else ""))
        return _il.import_module("nexen." + tgt)
    def exec_module(self, module):
        return None

_sys.meta_path.insert(0, _Alias())

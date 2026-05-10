"""Root conftest.py — ensures the parent of clockapp/ is on sys.path.

This allows `from clockapp.X import Y` to work whether pytest is invoked
from inside the clockapp/ directory or from the parent fleet-experimentation/
directory, and also in CI where the checkout dir is named 'world-history-clock'
rather than 'clockapp'.
"""
import sys
import types
from pathlib import Path

_here = Path(__file__).parent   # repo root — IS the clockapp package
_parent = _here.parent

# Works locally when the repo is cloned into a directory named 'clockapp'.
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

# In CI the checkout dir is 'world-history-clock', not 'clockapp', so there
# is no clockapp/ under _parent. Inject a lightweight shim so subpackage
# imports (clockapp.server.*, clockapp.data.*) resolve to the repo root.
if not (_parent / "clockapp").exists() and "clockapp" not in sys.modules:
    _pkg = types.ModuleType("clockapp")
    _pkg.__path__ = [str(_here)]
    _pkg.__package__ = "clockapp"
    sys.modules["clockapp"] = _pkg

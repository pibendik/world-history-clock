"""Root conftest.py — ensures the parent of clockapp/ is on sys.path.

This allows `from clockapp.X import Y` to work whether pytest is invoked
from inside the clockapp/ directory or from the parent fleet-experimentation/
directory.
"""
import sys
from pathlib import Path

# Insert the directory *containing* clockapp/ onto sys.path so that
# `import clockapp` resolves correctly.
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

"""Runtime guard: verify required packages are importable before doing anything.

Usage (add at top of every CLI script in backend/):

    from backend.env_guard import require

    require("pandas", "shioaji", "dotenv")   # dotenv = python-dotenv

If any package is missing the script exits immediately with a clear message
instead of a cryptic ImportError mid-run.
"""
from __future__ import annotations

import sys

_VENV_HINT = (
    "Activate the project venv first:\n"
    r"  (Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; "
    r"(& 'c:\Users\sfudally\Desktop\code test\tw-stock-signal\.venv\Scripts\Activate.ps1')"
)

# map install name → importable name (only needed when they differ)
_IMPORT_NAME = {
    "python-dotenv": "dotenv",
    "scikit-learn":  "sklearn",
    "Pillow":        "PIL",
}


def require(*packages: str) -> None:
    """Abort with a helpful message if any package cannot be imported."""
    missing = []
    for pkg in packages:
        import_name = _IMPORT_NAME.get(pkg, pkg)
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(
            f"\n[env_guard] Missing packages: {', '.join(missing)}\n"
            f"{_VENV_HINT}\n",
            file=sys.stderr,
        )
        sys.exit(1)

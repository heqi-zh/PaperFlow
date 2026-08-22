"""Resolution of the PaperFlow runtime root (where mutable state lives).

Every entry point used to derive runtime paths from ``Path(__file__).parents[N]``,
which is the repository root in a git checkout but the *site-packages directory*
in an installed wheel. That meant ``pip install paperflow && paperflow init``
created ``data/paperflow.db`` inside site-packages: lost on upgrade or
reinstall, and unwritable on a read-only or shared install.

Resolution order:

1. ``PAPERFLOW_HOME`` -- explicit override, always wins.
2. The source checkout, when one is detected. A wheel never installs
   ``pyproject.toml``, so its presence next to the package is a reliable
   checkout marker. This keeps the existing developer layout (``<repo>/data``)
   byte-for-byte unchanged.
3. ``~/.paperflow`` -- the installed-tool default.
"""

from __future__ import annotations

import os
from pathlib import Path

# paperflow/runtime.py -> paperflow/ -> <root>
_PACKAGE_PARENT = Path(__file__).resolve().parent.parent


def _looks_like_source_checkout(candidate: Path) -> bool:
    """True when candidate is a PaperFlow source tree rather than site-packages.

    Checked against pyproject.toml because wheels do not install it. The .git
    probe covers checkouts whose pyproject was moved or is unreadable.
    """
    if (candidate / "pyproject.toml").is_file():
        return True
    return (candidate / ".git").exists()


def paperflow_home() -> Path:
    """Return the directory that holds mutable runtime state."""
    override = os.environ.get("PAPERFLOW_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if _looks_like_source_checkout(_PACKAGE_PARENT):
        return _PACKAGE_PARENT

    return Path.home() / ".paperflow"


def data_dir() -> Path:
    """Return the runtime data directory, honoring PAPERFLOW_DATA_DIR."""
    override = os.environ.get("PAPERFLOW_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return paperflow_home() / "data"


def db_path() -> Path:
    """Return the SQLite database path, honoring PAPERFLOW_DB_PATH."""
    override = os.environ.get("PAPERFLOW_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return data_dir() / "paperflow.db"


def package_root() -> Path:
    """Return the directory containing the agents/, skills/ and config/ trees.

    This is where code lives, not where state is written -- the two coincide in
    a checkout but diverge in an installed wheel.
    """
    return _PACKAGE_PARENT

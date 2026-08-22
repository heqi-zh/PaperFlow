#!/usr/bin/env python3
"""Initialize local runtime directories and the SQLite database."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Where code lives (PROJECT_ROOT) and where runtime state belongs are the same
# directory in a source checkout but not in an installed wheel, where
# PROJECT_ROOT is site-packages. Writing data there loses it on upgrade.
try:
    from paperflow.runtime import data_dir as _resolve_data_dir
    from paperflow.runtime import paperflow_home as _resolve_home

    RUNTIME_ROOT = _resolve_home()
    DATA_DIR = _resolve_data_dir()
except Exception:
    RUNTIME_ROOT = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"


def ensure_runtime_dirs() -> None:
    for relative in (
        "db_backups",
        "embeddings_cache",
        "papers",
        "reading_reports",
        "wiki",
        "webhook_task_locks",
    ):
        (DATA_DIR / relative).mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_ROOT / "models").mkdir(parents=True, exist_ok=True)

    # .gitkeep only makes sense inside the repository; an installed runtime root
    # is not version controlled.
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        for path in (DATA_DIR / ".gitkeep", RUNTIME_ROOT / "models" / ".gitkeep"):
            path.touch(exist_ok=True)


def main() -> int:
    ensure_runtime_dirs()

    db_ops = importlib.import_module("skills.storage-helper.scripts.db_ops")
    db_ops.init_db()

    wiki_db = importlib.import_module("skills.wiki-store.scripts.wiki_db")
    wiki_db.init_wiki_schema()

    print(f"[OK] Runtime directories ready: {RUNTIME_ROOT}")
    print(f"[OK] Database ready: {db_ops.DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

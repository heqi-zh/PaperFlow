"""Shared environment-variable parsing.

These helpers existed in three copies (the Feishu daily-push agent, the desktop
GUI backend, and ad-hoc inline expressions in the reading and feedback agents)
with *different* semantics. The two boolean variants had opposite polarity:

    daily-push:  raw.strip().lower() not in {"0", "false", "off", "no"}
    desktop GUI: raw.strip().lower() in {"1", "true", "yes", "on"}

So an empty value (``PAPERFLOW_WIKI_INGEST=`` in .env) meant "enabled" to the
agents that do the ingesting and "disabled" to the GUI checkbox reporting it --
the settings panel contradicted actual behavior. Values like ``enabled`` or ``2``
diverged the same way.

The denylist reading wins here because it is what the shipped agents act on:
anything that is not an explicit negative counts as enabled. Blank is treated as
"unset" rather than as a negative, so it falls back to the caller's default
instead of silently disabling a feature.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence

FALSEY = frozenset({"0", "false", "off", "no", "n", "none"})
TRUTHY = frozenset({"1", "true", "on", "yes", "y"})


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag.

    Unset or blank yields ``default``. An explicit negative (0/false/off/no/n/
    none, case-insensitive) yields False. Anything else yields True, which keeps
    values like ``enabled`` working as the agents always treated them.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    text = raw.strip().lower()
    if not text:
        return default
    return text not in FALSEY


def env_int(
    name: str,
    default: int,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """Read an integer, clamped to the given bounds.

    A malformed value falls back to ``default`` rather than raising, because
    these are read during agent start-up where a hard failure is worse than a
    sane default.
    """
    raw = os.environ.get(name)
    try:
        value = int(str(raw).strip())
    except (AttributeError, TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def env_float(name: str, default: float) -> float:
    """Read a float, falling back to ``default`` when unset or malformed."""
    raw = os.environ.get(name)
    try:
        return float(str(raw).strip())
    except (AttributeError, TypeError, ValueError):
        return default


def env_list(name: str, default: Optional[Sequence[str]] = None) -> List[str]:
    """Read a list split on commas, semicolons, or newlines.

    Blank entries are dropped, so trailing separators are harmless.
    """
    raw = os.environ.get(name, "")
    items = [item.strip() for item in re.split(r"[,;\n]", raw) if item.strip()]
    if items:
        return items
    return [str(item) for item in (default or [])]


def env_text(name: str, default: str = "") -> str:
    """Read a stripped string, treating blank as unset."""
    return str(os.environ.get(name, "") or "").strip() or default

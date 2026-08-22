"""Tests for the shared environment-variable parsers.

These existed as three divergent copies. The two boolean variants had opposite
polarity, so the desktop settings panel could report a feature as disabled while
the agents acting on the same variable had it enabled.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from paperflow import env as shared_env  # noqa: E402


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "off", "no", "n", "none", " false "])
def test_explicit_negatives_are_false(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("PAPERFLOW_TEST_FLAG", raw)
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=True) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "on", "yes", "y", "enabled", "2"])
def test_non_negatives_are_true(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """Values like 'enabled' must stay truthy: the shipped agents treated any
    non-negative value as enabled, and the GUI has to agree with them."""
    monkeypatch.setenv("PAPERFLOW_TEST_FLAG", raw)
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=False) is True


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """`FLAG=` in .env means unset, not disabled.

    The old GUI parser read blank as False, which silently disabled features the
    agents still performed.
    """
    monkeypatch.setenv("PAPERFLOW_TEST_FLAG", raw)
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=True) is True
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=False) is False


def test_unset_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAPERFLOW_TEST_FLAG", raising=False)
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=True) is True
    assert shared_env.env_bool("PAPERFLOW_TEST_FLAG", default=False) is False


def test_wiki_ingest_flag_agrees_across_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """PAPERFLOW_WIKI_INGEST is read by four modules; they must not disagree."""
    reading_agent = importlib.import_module("agents.reading-agent.main")
    feedback_agent = importlib.import_module("agents.feedback-agent.main")
    daily_push = importlib.import_module("deployments.feishu.daily-push-agent.main")
    gui = importlib.import_module("deployments.desktop.shared.agents")

    for raw in ["", "1", "true", "0", "false", "enabled", "off"]:
        monkeypatch.setenv("PAPERFLOW_WIKI_INGEST", raw)
        verdicts = {
            reading_agent._wiki_ingest_enabled(),
            feedback_agent._wiki_ingest_enabled(),
            daily_push._wiki_ingest_enabled(),
            gui._env_bool("PAPERFLOW_WIKI_INGEST", default=True),
        }
        assert len(verdicts) == 1, f"entry points disagree for PAPERFLOW_WIKI_INGEST={raw!r}"


def test_env_int_clamps_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERFLOW_TEST_INT", "42")
    assert shared_env.env_int("PAPERFLOW_TEST_INT", 5) == 42
    assert shared_env.env_int("PAPERFLOW_TEST_INT", 5, max_value=10) == 10
    assert shared_env.env_int("PAPERFLOW_TEST_INT", 5, min_value=100) == 100

    monkeypatch.setenv("PAPERFLOW_TEST_INT", "not-a-number")
    assert shared_env.env_int("PAPERFLOW_TEST_INT", 7) == 7

    monkeypatch.delenv("PAPERFLOW_TEST_INT", raising=False)
    assert shared_env.env_int("PAPERFLOW_TEST_INT", 7) == 7


def test_env_float_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERFLOW_TEST_FLOAT", "0.25")
    assert shared_env.env_float("PAPERFLOW_TEST_FLOAT", 1.0) == 0.25

    monkeypatch.setenv("PAPERFLOW_TEST_FLOAT", "abc")
    assert shared_env.env_float("PAPERFLOW_TEST_FLOAT", 1.5) == 1.5


def test_env_list_splits_on_all_separators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERFLOW_TEST_LIST", "cs.CL, cs.AI;cs.LG\ncs.IR")
    assert shared_env.env_list("PAPERFLOW_TEST_LIST") == ["cs.CL", "cs.AI", "cs.LG", "cs.IR"]

    # Trailing and repeated separators must not yield blank entries.
    monkeypatch.setenv("PAPERFLOW_TEST_LIST", "a,,b; ,")
    assert shared_env.env_list("PAPERFLOW_TEST_LIST") == ["a", "b"]

    monkeypatch.setenv("PAPERFLOW_TEST_LIST", "")
    assert shared_env.env_list("PAPERFLOW_TEST_LIST", default=["fallback"]) == ["fallback"]


def test_env_text_treats_blank_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERFLOW_TEST_TEXT", "  value  ")
    assert shared_env.env_text("PAPERFLOW_TEST_TEXT") == "value"

    monkeypatch.setenv("PAPERFLOW_TEST_TEXT", "   ")
    assert shared_env.env_text("PAPERFLOW_TEST_TEXT", "fallback") == "fallback"

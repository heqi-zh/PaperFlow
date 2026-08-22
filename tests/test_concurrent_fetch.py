"""Tests for the concurrent fetch paths.

These cover the invariants that concurrency can silently break: output ordering
(dedup downstream keeps the first occurrence), per-source error isolation, and
the embedding hash-fallback contract.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

journal_fetcher = importlib.import_module("skills.journal-fetcher.scripts.fetch_journal")
embed_module = importlib.import_module("skills.embedding.scripts.embed")


def test_journal_results_keep_requested_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order must survive parallelism: dedup keeps the first copy of a paper."""
    order = ["nature", "science", "cell", "pnas"]

    def fake_fetch(journal: str, limit: int, days: int):
        # Finish in reverse order so a naive as_completed collection would scramble.
        time.sleep(0.05 * (len(order) - order.index(journal)))
        return [{"title": f"{journal}-paper", "doi": f"10.0/{journal}"}]

    monkeypatch.setattr(journal_fetcher, "fetch_journal_papers", fake_fetch)

    papers = journal_fetcher.get_recent_papers(journals=order, days=3, limit_per_journal=5)

    assert [paper["title"] for paper in papers] == [f"{name}-paper" for name in order]


def test_one_failing_journal_does_not_abort_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(journal: str, limit: int, days: int):
        if journal == "science":
            raise RuntimeError("feed unreachable")
        return [{"title": f"{journal}-paper", "doi": f"10.0/{journal}"}]

    monkeypatch.setattr(journal_fetcher, "fetch_journal_papers", fake_fetch)

    papers = journal_fetcher.get_recent_papers(
        journals=["nature", "science", "cell"], days=3, limit_per_journal=5
    )

    assert [paper["title"] for paper in papers] == ["nature-paper", "cell-paper"]


def test_journal_fetch_actually_runs_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards against a refactor quietly collapsing back to a serial loop."""
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake_fetch(journal: str, limit: int, days: int):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.1)
        with lock:
            active["now"] -= 1
        return []

    monkeypatch.setattr(journal_fetcher, "fetch_journal_papers", fake_fetch)
    journal_fetcher.get_recent_papers(
        journals=["nature", "science", "cell", "pnas"], days=3, limit_per_journal=5
    )

    assert active["peak"] > 1, "journals were fetched serially"


def test_single_journal_skips_the_thread_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_fetch(journal: str, limit: int, days: int):
        calls.append(threading.current_thread().name)
        return []

    monkeypatch.setattr(journal_fetcher, "fetch_journal_papers", fake_fetch)
    journal_fetcher.get_recent_papers(journals=["nature"], days=3, limit_per_journal=5)

    assert calls == [threading.main_thread().name]


def test_journal_concurrency_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERFLOW_JOURNAL_CONCURRENCY", "3")
    assert journal_fetcher._journal_fetch_concurrency(10) == 3

    # Never more workers than there is work, and never zero.
    assert journal_fetcher._journal_fetch_concurrency(2) == 2
    assert journal_fetcher._journal_fetch_concurrency(1) == 1

    monkeypatch.setenv("PAPERFLOW_JOURNAL_CONCURRENCY", "not-a-number")
    assert journal_fetcher._journal_fetch_concurrency(10) == 6


def test_embed_batch_preserves_input_order_across_batches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Vectors are written by index, so a scrambled completion order is fine --
    but the returned list must still line up with the input texts."""
    service = embed_module.EmbeddingService.__new__(embed_module.EmbeddingService)
    service.provider = "openai"
    service.model = "test-model"
    service.dimensions = 4
    service.cache_dir = tmp_path

    class FakeEmbeddings:
        @staticmethod
        def create(model, input, **kwargs):
            # Later batches return faster.
            time.sleep(0.02 / (len(input) or 1))

            class Item:
                def __init__(self, value):
                    self.embedding = [float(value)] * 4

            return type("Resp", (), {"data": [Item(int(text.split("-")[1])) for text in input]})()

    service.client = type("Client", (), {"embeddings": FakeEmbeddings})()

    texts = [f"text-{index}" for index in range(10)]
    vectors = service.embed_batch(texts, batch_size=3)

    assert [vector[0] for vector in vectors] == [float(index) for index in range(10)]


def test_embed_batch_falls_back_to_hash_for_every_text_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The serial loop degraded to hash embeddings for all missing indices when a
    request failed; the parallel version must not leave holes."""
    service = embed_module.EmbeddingService.__new__(embed_module.EmbeddingService)
    service.provider = "openai"
    service.model = "test-model"
    service.dimensions = 8
    service.cache_dir = tmp_path

    class FailingEmbeddings:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("401 invalid api key")

    service.client = type("Client", (), {"embeddings": FailingEmbeddings})()

    vectors = service.embed_batch([f"text-{index}" for index in range(20)], batch_size=3)

    assert service.provider == "hash"
    assert service.model == "hash"
    assert len(vectors) == 20
    assert all(len(vector) == 8 for vector in vectors)


def test_embed_concurrency_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    service = embed_module.EmbeddingService.__new__(embed_module.EmbeddingService)

    monkeypatch.setenv("PAPERFLOW_EMBED_CONCURRENCY", "2")
    assert service._batch_concurrency(10) == 2

    assert service._batch_concurrency(1) == 1

    monkeypatch.setenv("PAPERFLOW_EMBED_CONCURRENCY", "")
    assert service._batch_concurrency(10) == 4

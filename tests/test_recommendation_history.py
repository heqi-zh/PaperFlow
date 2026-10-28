import importlib

import pytest

from deployments.desktop.shared import agents

daily = importlib.import_module("deployments.feishu.daily-push-agent.main")


def test_only_handling_actions_exclude_papers_not_shown_or_later(test_db_path, sample_paper, monkeypatch):
    db = daily.db_ops
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    papers = []
    for i, action in enumerate(["pushed", "later", "selected", "skipped", "created_report"]):
        p = dict(sample_paper, arxiv_id=f"2610.{20000+i}", doi=f"10.test/{i}", title=f"Paper {i}")
        pid = db.add_paper(p)
        db.log_behavior("alice", "batch", pid, action, action, "test")
        papers.append({"arxiv_id": p["arxiv_id"] + "v2", "title": p["title"]})
    result, dropped = daily.filter_user_handled_papers("alice", papers)
    assert result == papers[:2]
    assert dropped == 3
    assert daily.filter_user_handled_papers("bob", papers)[1] == 0


def test_history_is_user_scoped_and_keeps_feedback_numbering(test_db_path, sample_paper, monkeypatch):
    db = agents.db_ops
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    p1 = db.add_paper(dict(sample_paper, arxiv_id="2610.30001", title="First", doi="10.test/a"))
    p2 = db.add_paper(dict(sample_paper, arxiv_id="2610.30002", title="Second", doi="10.test/b"))
    p3 = db.add_paper(dict(sample_paper, arxiv_id="2610.30003", title="Other user", doi="10.test/c"))
    # Legacy batches could share an id between users; never leak those rows.
    db.log_behavior("alice", "same_id", p1, "pushed", "push", "high_relevant", metadata={"rank": 1})
    db.log_behavior("alice", "same_id", p2, "pushed", "push", "high_relevant", metadata={"rank": 2})
    db.log_behavior("bob", "same_id", p3, "pushed", "push", "high_relevant", metadata={"rank": 1})
    db.log_behavior("bob", "private", p3, "pushed", "push", "high_relevant")
    db.log_behavior("alice", "empty", None, "push_empty", "push", "empty_push")
    history = agents.list_push_history("alice")["batches"]
    assert [x["push_id"] for x in history] == ["empty", "same_id"]
    assert [x["paper_count"] for x in history] == [0, 2]
    push = agents.load_history_push("alice", "same_id")["push"]
    assert push["metadata"]["history_view"] is True
    assert [p["title"] for p in push["papers"]] == ["First", "Second"]
    assert [p["number"] for p in push["papers"]] == [1, 2]
    with pytest.raises(ValueError):
        agents.load_history_push("alice", "private")

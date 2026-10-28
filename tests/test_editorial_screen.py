import json
from types import SimpleNamespace

from paperflow.editorial import review_candidates
from paperflow.recommendations import profile_fingerprint


PROFILE = {"editorial_preferences": {"core": "Agent navigation and LiDAR surfaces", "skip": "RL navigation"}}


class Editor:
    name = "test"
    calls = 0

    def __init__(self, **changes):
        self.changes = changes

    def generate(self, prompt, **kwargs):
        self.calls += 1
        source = json.loads(prompt.split("\n", 1)[1])["papers"]
        return SimpleNamespace(text=json.dumps([dict(
            id=p["id"], decision="keep", track="core", relevance=.95, contribution=.85,
            reason_zh="基于空间记忆与工具规划的导航方法。", evidence=p["abstract"][:100],
            navigation_mode="not_navigation", primary_method="other", independent_core_contribution=True,
        ) | self.changes for p in reversed(source)]))


def test_editorial_evidence_cache_invalidates_with_preferences_and_abstract(tmp_path):
    editor = Editor()
    paper = {"title": "Agent navigation", "abstract": "Spatial memory enables explicit tool planning."}
    kept, meta = review_candidates([dict(paper)], PROFILE, provider=editor, cache_dir=tmp_path)
    assert len(kept) == 1 and meta["filtered_editorial"] == 0
    assert kept[0]["recommendation_review"]["verification"] == "abstract_only"
    review_candidates([dict(paper)], PROFILE, provider=editor, cache_dir=tmp_path)
    assert editor.calls == 1
    updated = {"editorial_preferences": {"core": "FMCW LiDAR"}}
    assert profile_fingerprint(PROFILE) != profile_fingerprint(updated)
    review_candidates([dict(paper)], updated, provider=editor, cache_dir=tmp_path)
    review_candidates([dict(paper, abstract="Changed contribution.")], updated, provider=editor, cache_dir=tmp_path)
    assert editor.calls == 3


def test_selective_topics_need_stronger_evidence_and_missing_abstract_cannot_pass(tmp_path):
    paper = {"title": "A generic VLA", "abstract": "A small improvement."}
    kept, meta = review_candidates([paper], PROFILE, provider=Editor(track="selective", contribution=.6), cache_dir=tmp_path)
    assert kept == [] and meta["filtered_editorial"] == 1
    assert paper["recommendation_review"]["decision"] == "watch"
    paper = {"title": "Claimed major breakthrough", "abstract": ""}
    assert review_candidates([paper], PROFILE, provider=Editor(), cache_dir=tmp_path)[0] == []


def test_fabricated_evidence_or_nonfinite_scores_fail_closed(tmp_path):
    for change in [{"evidence": "Invented supporting claim"}, {"relevance": float("nan")}]:
        paper = {"title": "Agent navigation", "abstract": "Actual source."}
        kept, meta = review_candidates([paper], PROFILE, provider=Editor(**change), cache_dir=tmp_path)
        assert kept == []
        assert meta["editorial_unavailable"] == 1
    assert not list(tmp_path.glob("*.json"))


def test_failed_editor_is_retryable_and_does_not_restore_weak_candidates(tmp_path):
    class Offline:
        name = "test"
        def generate(self, *args, **kwargs): raise RuntimeError("offline")
    paper = {"title": "Agent navigation", "abstract": "Agent planning with memory."}
    assert review_candidates([paper], PROFILE, provider=Offline(), cache_dir=tmp_path)[0] == []
    assert not list(tmp_path.iterdir())
    assert review_candidates([paper], PROFILE, provider=Editor(), cache_dir=tmp_path)[0] == [paper]


def test_legacy_profiles_do_not_require_an_editor(tmp_path):
    papers = [{"title": "Legacy paper"}]
    assert review_candidates(papers, {}, cache_dir=tmp_path)[0] is papers


def test_rl_policy_memory_does_not_pass_as_agent_navigation_even_with_high_scores(tmp_path):
    preferences = {"editorial_preferences": {"gates": {
        "navigation_mode": "agentic", "skip_primary_methods": ["rl_policy", "rsi_loop"],
    }}}
    paper = {"title": "Navigation memory", "abstract": "Spatial memory for an end-to-end RL policy."}
    editor = Editor(navigation_mode="policy", primary_method="rl_policy", independent_core_contribution=True)
    assert review_candidates([paper], preferences, provider=editor, cache_dir=tmp_path)[0] == []
    assert paper["recommendation_review"]["decision"] == "skip"


def test_rsi_is_allowed_only_with_an_independent_core_contribution(tmp_path):
    preferences = {"editorial_preferences": {"gates": {"skip_primary_methods": ["rsi_loop"]}}}
    paper = {"title": "Robot reasoning", "abstract": "A new spatial representation with optional self improvement."}
    assert review_candidates([dict(paper)], preferences, provider=Editor(primary_method="rsi_loop", independent_core_contribution=False), cache_dir=tmp_path / "a")[0] == []
    assert review_candidates([dict(paper)], preferences, provider=Editor(primary_method="rsi_loop", independent_core_contribution=True), cache_dir=tmp_path / "b")[0]

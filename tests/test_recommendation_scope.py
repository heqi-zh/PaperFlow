import importlib
import json
from types import SimpleNamespace

from paperflow.recommendations import scope_match, profile_fingerprint
from paperflow.translations import translate_papers

agent = importlib.import_module("deployments.feishu.daily-push-agent.main")


def profile():
    return {"recommendation_scope": {
        "focus_groups": [{"label": "Spatial", "weight": 1, "terms": ["reconstruction", "SLAM", "robot agents"]}],
        "exclude_terms": ["medical", "CT", "tomography"],
    }}


def test_explicit_scope_overrides_gaussian_medical_overlap_and_short_token_boundaries():
    assert not scope_match({"title": "CT volume reconstruction with Gaussian splatting"}, profile())[0]
    assert not scope_match({"title": "3D reconstruction", "abstract": "A method for medical imaging"}, profile())[0]
    assert scope_match({"title": "ACT robot agents for SLAM reconstruction"}, profile())[0]
    assert not scope_match({"title": "Random visual analytics"}, profile())[0]
    assert scope_match({"title": "Random visual analytics"}, {})[0]


def test_medical_must_read_cannot_bypass_scope_or_fallback(monkeypatch):
    monkeypatch.setattr(agent, "is_must_read", lambda *a: True)
    forbidden = [{"title": "CT reconstruction", "score": 1.0}]
    assert agent.sort_and_categorize(forbidden, profile(), {}) == []
    assert agent.build_relaxed_fallback_scores(forbidden, profile(), {}) == []


def test_seen_history_is_per_user_and_deduplicates_versions_doi_and_title(test_db_path, sample_paper):
    db = agent.db_ops
    db.DB_PATH = test_db_path
    paper = dict(sample_paper, arxiv_id="2606.12345v1", doi="10.1234/test", title="Spatial-Reconstruction: A Method")
    pid = db.add_paper(paper)
    db.log_behavior("alice", "old", pid, "pushed", "push", "high_relevant")
    candidates = [
        {"arxiv_id": "2606.12345v2", "title": "Revised Title"},
        {"doi": "https://doi.org/10.1234/TEST", "title": "Different Title"},
        {"title": "Spatial reconstruction — a method"},
        {"title": "New robot agents"},
    ]
    remaining, dropped = agent.filter_user_handled_papers("alice", candidates)
    assert dropped == 3
    assert remaining == [candidates[-1]]
    assert agent.filter_user_handled_papers("bob", candidates)[1] == 0


def test_cache_identity_changes_with_research_scope_but_not_timestamp():
    a = profile()
    b = json.loads(json.dumps(a))
    b["updated_at"] = "later"
    assert profile_fingerprint(a) == profile_fingerprint(b)
    b["recommendation_scope"]["exclude_terms"].append("MRI")
    assert profile_fingerprint(a) != profile_fingerprint(b)


class Translator:
    name = "test"
    calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        source = json.loads(prompt.split("\n", 1)[1])
        return SimpleNamespace(text=json.dumps([
            {"id": x["id"], "title_zh": "空间重建", "abstract_zh": "完整中文摘要。" if x["abstract"] else "虚构摘要"}
            for x in reversed(source)
        ]))


def test_translation_matches_content_ids_caches_and_invalidates_changed_abstract(tmp_path):
    provider = Translator()
    paper = {"title": "Spatial reconstruction", "abstract": "Full original."}
    missing = {"title": "Robot agents", "abstract": ""}
    translate_papers([paper, missing], provider=provider, cache_dir=tmp_path)
    assert paper["title_zh"] == "空间重建"
    assert paper["abstract"] == "Full original."
    assert missing["abstract_zh"] == ""  # Never invent absent source text.
    translate_papers([dict(paper)], provider=provider, cache_dir=tmp_path)
    assert provider.calls == 1
    translate_papers([dict(paper, abstract="Changed abstract")], provider=provider, cache_dir=tmp_path)
    assert provider.calls == 2


def test_translation_failure_keeps_original_and_does_not_poison_cache(tmp_path):
    class Failing:
        name = "test"
        def generate(self, *args, **kwargs):
            raise RuntimeError("Offline")
    paper = {"title": "Original", "abstract": "Original abstract"}
    translate_papers([paper], provider=Failing(), cache_dir=tmp_path)
    assert paper["title"] == "Original"
    assert paper["translation_status"] == "unavailable"
    assert list(tmp_path.iterdir()) == []
    translate_papers([paper], provider=Translator(), cache_dir=tmp_path)
    assert paper["translation_status"] == "complete"


def test_daily_refresh_never_repeats_shown_papers_or_reuses_previous_nonempty_batch(test_db_path, monkeypatch):
    db = agent.db_ops
    db.DB_PATH = test_db_path
    db.create_profile("refresh-test", dict(profile(), user_id="refresh-test"))
    candidates = [
        {"arxiv_id": "2610.12345", "title": "SLAM reconstruction", "abstract": "Robot SLAM."},
        {"arxiv_id": "2610.12346", "title": "CT reconstruction", "abstract": "Medical CT."},
    ]
    monkeypatch.setattr(agent, "fetch_and_process_papers", lambda **kw: [dict(p) for p in candidates])
    monkeypatch.setattr(agent, "sort_and_categorize", lambda papers, *a, **kw: [
        agent.PaperWithScore(paper=p, score=.8, category="high_relevant", relevance_signal=.8) for p in papers
    ])
    monkeypatch.setattr(agent, "translate_papers", lambda papers: [p.update(title_zh="场景重建", abstract_zh="机器人建图。", translation_status="complete") for p in papers])
    monkeypatch.setattr(agent, "ingest_pushed_paper_to_wiki", lambda **kw: None)
    monkeypatch.setenv("PAPERFLOW_ALLOW_STALE_DAILY_FALLBACK", "false")
    first = agent.daily_push("refresh-test", arxiv_categories=["cs.RO"], conferences=[], journals=[])
    assert first["paper_count"] == 1
    assert first["filtered_scope"] == 1
    stored = db.get_push_papers(first["push_id"])
    assert stored["papers"][0]["title_zh"] == "场景重建"
    second = agent.daily_push("refresh-test", arxiv_categories=["cs.RO"], conferences=[], journals=[])
    assert second["paper_count"] == 0
    assert second["filtered_seen"] == 1
    assert first["push_id"] != second["push_id"]
    assert db.get_latest_push("refresh-test")["push_id"] == second["push_id"]
    assert db.get_latest_push("refresh-test")["papers"] == []


def test_compound_focus_requires_both_dynamic_and_reconstruction():
    p = {"recommendation_scope": {"focus_groups": [
        {"label": "4D", "all_terms": [["dynamic", "reconstruction"]], "weight": 1},
    ]}}
    assert scope_match({"title": "Dynamic scene reconstruction"}, p)[0]
    assert not scope_match({"title": "Dynamic radar simulation"}, p)[0]

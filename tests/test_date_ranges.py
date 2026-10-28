from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

journal = importlib.import_module("skills.journal-fetcher.scripts.fetch_journal")
daily = importlib.import_module("deployments.feishu.daily-push-agent.main")
ROOT = Path(__file__).resolve().parents[1]


def test_tvcg_uses_public_metadata_and_inclusive_historical_range(monkeypatch):
    calls = []
    def query(endpoint, params):
        calls.append((endpoint, params))
        return [{"title": [str(day)], "DOI": f"10.test/{day}", "published-online": {"date-parts": [[2026, 10, day]]}}
                for day in [18, 19, 25, 26]]
    monkeypatch.setattr(journal, "query_crossref_works", query)
    papers = journal.get_recent_papers(days=7, journals=["IEEE Transactions on Visualization and Computer Graphics"], end_date="2026-10-25")
    assert [p["title"] for p in papers] == ["19", "25"]
    assert all(p["venue"] == "TVCG" for p in papers)
    assert calls[0][0].endswith("/journals/1077-2626/works")
    assert calls[0][1]["filter"] == "from-pub-date:2026-10-19,until-pub-date:2026-10-25"
    assert journal._journal_date_window(1, "2026-10-25") == (datetime(2026,10,25), datetime(2026,10,25))


def test_arxiv_and_journal_receive_the_same_chosen_window(monkeypatch):
    captured = {}
    def arxiv(**kwargs):
        captured["arxiv"] = kwargs
        return [{"title": "Reconstruction", "arxiv_id": "2610.10001", "publish_date": "2026-10-22"}]
    def journals(**kwargs):
        captured["journal"] = kwargs
        return [{"title": "Mesh reconstruction", "doi": "10.test/mesh", "publish_date": "2026-10-24"}]
    monkeypatch.setattr(daily, "arxiv_fetch_by_date", arxiv)
    monkeypatch.setattr(daily, "journal_fetch_recent", journals)
    monkeypatch.setattr(daily, "prepare_paper_features", lambda papers: papers)
    papers = daily.fetch_and_process_papers(days=7, target_date="2026-10-25", arxiv_categories=["cs.CV"], conferences=[], journals=["TVCG"])
    assert len(papers) == 2
    assert captured["arxiv"]["start_date"] == "20261019"
    assert captured["arxiv"]["end_date"] == "20261025"
    assert captured["journal"]["days"] == 7
    assert captured["journal"]["end_date"] == "2026-10-25"


def test_daily_http_route_preserves_days_independently_of_end_date(monkeypatch):
    from deployments.desktop import server
    captured = {}
    monkeypatch.setattr(server.agents, "start_daily_push_task", lambda **kw: captured.update(kw) or {"task": {}})
    server.POST_ROUTES["/api/daily/start"]({}, {"user_id": "test", "target_date": "2026-10-25", "days": 7})
    assert captured["days"] == 7 and captured["target_date"] == "2026-10-25"


def test_actual_browser_date_controls_do_not_override_days_and_show_correct_window():
    node = shutil.which("node") or os.environ.get("PAPERFLOW_NODE")
    if not node or not Path(node).exists():
        pytest.skip("Node.js is required for executing the actual GUI date-control functions")
    source = (ROOT / "deployments/desktop/static/desktop.js").read_text()
    functions = source.split("  function dateFromInputValue(value) {", 1)[1].split("  function setDailyTaskState", 1)[0]
    script = "function dateFromInputValue(value) {" + functions
    script += """
const state = {dailyPolling:false, language:'zh'};
const controls = {paperDate:{value:'2026-10-28'},daysInput:{value:'7'},runDailyBtn:{},dateRangeHint:{}};
const $ = (id) => controls[id];
const document = {querySelectorAll:()=>[]};
const ui = () => ({papers:{pullToday:'new',pullSelected:'range'}});
const todayDateValue = () => '2026-11-10';
const results=[];
for (const [end,days] of [['2026-10-28','7'],['2026-10-25','7'],['2026-10-25','1'],['2026-11-02','3']]) {
  controls.paperDate.value=end;
  controls.daysInput.value=days;
  syncDateControls();
  results.push([controls.daysInput.value,controls.dateRangeHint.textContent]);
}
process.stdout.write(JSON.stringify(results));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, env={**os.environ, "TZ":"America/New_York"})
    values = json.loads(result.stdout)
    assert values == [
        ["7", "2026-10-22 — 2026-10-28 · 7 天（含首尾）"],
        ["7", "2026-10-19 — 2026-10-25 · 7 天（含首尾）"],
        ["1", "2026-10-25 — 2026-10-25 · 1 天（含首尾）"],
        ["3", "2026-10-31 — 2026-11-02 · 3 天（含首尾）"],
    ]


def test_daily_range_does_not_treat_annual_conference_catalog_as_recent_papers(monkeypatch):
    monkeypatch.setattr(daily, "openreview_fetch_by_date", lambda **kwargs: [
        {"title": "Annual TOC", "publish_date": "2026-01-01", "publish_date_precision": "year"},
        {"title": "No date", "publish_date": ""},
        {"title": "Old dated paper", "publish_date": "2026-06-01"},
        {"title": "Recent accepted paper", "publish_date": "2026-10-24"},
    ])
    monkeypatch.setattr(daily, "prepare_paper_features", lambda papers: papers)
    papers = daily.fetch_and_process_papers(days=7, target_date="2026-10-25", arxiv_categories=[], conferences=["ICRA"], journals=[])
    assert [paper["title"] for paper in papers] == ["Recent accepted paper"]

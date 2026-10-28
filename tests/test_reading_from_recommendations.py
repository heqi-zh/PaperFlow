import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from deployments.desktop.shared import agents

ROOT = Path(__file__).resolve().parents[1]


def test_actual_card_reading_starts_one_paper_without_manual_id_or_flushing_other_choices():
    node = shutil.which("node") or os.environ.get("PAPERFLOW_NODE")
    if not node or not Path(node).exists():
        pytest.skip("Node.js required for executing actual frontend reading functions")
    source = (ROOT / "deployments/desktop/static/desktop.js").read_text()
    functions = "async function readSinglePaper(number) {" + source.split("  async function readSinglePaper(number) {", 1)[1].split("  function renderMarkdown", 1)[0]
    stubs = r"""
const state = {push:{push_id:'history-batch',papers:[{number:1,title:'Selected title'},{number:2,title:'Other queued paper'}]},
 selected:new Set([2]),skipped:new Set([3]),later:new Set([4]),paperReports:new Map(),paperReading:new Set()};
const requests=[], opened=[];
const ui=()=>({papers:{loadPushFirst:'missing', chooseReadTitle:'choose',chooseReadDetail:'',chooseReadToast:'',submitFailed:'failed'}});
const currentUser=()=> 'reader';
const paperReportKey=(n,pushId=state.push.push_id)=> `reader::${pushId}::${n}`;
const $=()=>null;
const responseLanguage=()=> 'zh';
const ensureLlmReadyForReading=async()=>true;
const updateReadButtons=()=>{};
const updateSelectionSummary=()=>{};
const setSubmitButtonsBusy=()=>{};
const showPaperFeedback=()=>{};
const showFeedbackToast=()=>{};
const showSubmitResult=()=>{};
const loadWiki=async()=>{};
const setView=()=>{};
const openReport=async(id)=>opened.push(id);
const pollReadingTask=async()=>{};
const api=async(endpoint,options)=>{
 requests.push({endpoint,body:JSON.parse(options.body)});
 return {reports:{created_docs:[{report_id:'report-one'}],task:{task_id:'reading-task'}}};
};
"""
    script = stubs + functions + r"""
(async()=>{
 const first=readSinglePaper(1);
 const duplicate=readSinglePaper(1);
 await Promise.all([first,duplicate]);
 await readSinglePaper(1); // Existing report opens, never starts another job.
 process.stdout.write(JSON.stringify({requests,opened,selected:[...state.selected],skipped:[...state.skipped],later:[...state.later],busy:state.paperReading.size}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert len(data["requests"]) == 1
    request = data["requests"][0]
    assert request["endpoint"] == "/api/submit"
    assert request["body"]["push_id"] == "history-batch"
    assert request["body"]["selected_numbers"] == [1]
    assert request["body"]["skipped_numbers"] == [] and request["body"]["later_numbers"] == []
    assert "arxiv_id" not in request["body"]
    assert data["selected"] == [2] and data["skipped"] == [3] and data["later"] == [4]
    assert data["opened"] == ["report-one", "report-one"]
    assert data["busy"] == 0


def test_background_reading_resolves_saved_non_arxiv_paper_without_manual_identifier(test_db_path, sample_paper, tmp_path, monkeypatch):
    db = agents.db_ops
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    paper = dict(sample_paper, arxiv_id=None, doi="10.test/mesh", title="Journal mesh reconstruction")
    pid = db.add_paper(paper)
    db.log_behavior("reader", "saved-batch", pid, "pushed", "push", "high_relevant", metadata={
        "rank": 1,"url":"https://doi.org/10.test/mesh","pdf_url":"https://publisher.example/mesh.pdf"})
    monkeypatch.setattr(agents, "_configured_path", lambda *args: str(tmp_path / "reports"))
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(agents.threading, "Thread", Thread)
    result = agents.start_reading_reports_task(user_id="reader",push_id="saved-batch",paper_numbers=[1])
    assert result["count"] == 1 and result["task"]["status"] == "queued"
    doc = result["created_docs"][0]
    assert doc["paper"]["title"] == paper["title"]
    assert doc["paper"]["doi"] == paper["doi"]
    assert doc["paper"]["pdf_url"] == "https://publisher.example/mesh.pdf"
    assert Path(doc["report_path"]).exists()


def test_reading_placeholder_never_overwrites_a_finished_report(tmp_path):
    path = tmp_path / "report.md"
    original = "---\nreport_version: Q1-Q7\ngeneration_provider: chatgpt\n---\n# Existing report\nActual findings.\n"
    path.write_text(original)
    agents._write_reading_placeholder(user_id="reader",paper={"title":"Paper"},report_path=path,status="queued",steps=["queued"])
    agents._write_reading_placeholder(user_id="reader",paper={"title":"Paper"},report_path=path,status="failed",steps=["failed"])
    assert path.read_text() == original


def test_chinese_report_uses_translated_abstract_and_never_leaks_raw_source_fallback():
    reading = agents.reading_agent
    paper = {"title": "English original title", "abstract": "We reconstruct a detailed surface from multi view images using an adaptive spatial representation."}
    payload = {
        "response_language": "zh", "title_zh": "基于自适应空间表示的表面重建",
        "generation_provider": "chatgpt", "generation_model": "test",
        "abstract": paper["abstract"], "clean_abstract_summary": "本文利用自适应空间表示，从多视角图像中重建精细表面。",
        "problem_analysis": "研究重点在于提高三维表面重建效率。",
        "core_method": "We reconstruct a detailed surface from multi view images using an adaptive spatial representation.",
        "keywords": ["表面重建", "surface reconstruction"], "report_style": "deep",
    }
    report = reading.generate_reading_report(paper, {}, report_payload=payload)
    assert "# 基于自适应空间表示的表面重建" in report
    assert "本文利用自适应空间表示" in report
    assert "English original title" not in report and paper["abstract"] not in report
    assert "Deep-Dive Checklist" not in report and "surface reconstruction" not in report
    assert "## 精读重点" in report and "研究重点在于" in report
    fallback = reading.generate_reading_report(paper, {}, report_payload={
        "response_language": "zh", "generation_provider": "heuristic", "abstract": paper["abstract"],
        "one_sentence_summary": paper["abstract"], "core_method": paper["abstract"],
    })
    assert paper["abstract"] not in fallback
    assert "中文精读生成未成功" in fallback


def test_report_api_prefers_chinese_display_title_without_losing_original(tmp_path):
    path = tmp_path / "report.md"
    path.write_text('---\ntitle: Original title\ntitle_zh: 中文标题\n---\n# 中文标题\n\n中文正文。\n')
    record = agents._report_record(path)
    assert record["title"] == "中文标题"
    assert record["metadata"]["title"] == "Original title"

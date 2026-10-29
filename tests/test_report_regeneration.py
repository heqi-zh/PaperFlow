from contextlib import nullcontext
from pathlib import Path

import pytest

from deployments.desktop.shared import agents


@pytest.fixture
def existing_report(tmp_path, monkeypatch):
    path = tmp_path / 'reports' / 'old-report.md'
    path.parent.mkdir()
    path.write_text('---\nuser_id: reader\ntitle: Original paper\narxiv_id: "2610.00001"\nreport_version: old\ngeneration_provider: heuristic\n---\n# 旧版报告\n旧内容。\n')
    monkeypatch.setattr(agents, '_reading_report_dirs', lambda: [path.parent])
    monkeypatch.setattr(agents, 'data_dir', lambda: tmp_path / 'data')
    monkeypatch.setattr(agents, '_READING_TASKS', {})
    monkeypatch.setattr(agents, '_reading_agent_output_env_patch', lambda: nullcontext())
    monkeypatch.setattr(agents, '_local_only_feishu_doc_patch', lambda *a: nullcontext())
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(agents.threading, 'Thread', Thread)
    agents.invalidate_report_cache()
    return path, agents._report_record(path)['report_id']


def test_regeneration_reuses_source_ids_and_deduplicates_queued_work(existing_report):
    path, report_id = existing_report
    original = path.read_bytes()
    first = agents.start_report_regeneration(user_id='reader', report_id=report_id)
    second = agents.start_report_regeneration(user_id='reader', report_id=report_id)
    assert second['already_running'] is True
    assert first['task']['task_id'] == second['task']['task_id']
    assert len(agents._READING_TASKS) == 1
    assert agents._READING_TASKS[first['task']['task_id']]['internal_docs'][0]['paper_raw']['arxiv_id'] == '2610.00001'
    assert path.read_bytes() == original  # No loading page replaces the report.
    record = agents.get_report_content(report_id)['report']
    assert record['can_regenerate'] is True
    assert record['regeneration_task']['status'] == 'queued'
    with pytest.raises(ValueError, match='当前用户'):
        agents.start_report_regeneration(user_id='other', report_id=report_id)


def test_regeneration_failure_restores_original_and_allows_retry(existing_report, monkeypatch):
    path, report_id = existing_report
    original = path.read_bytes()
    def failed_generation(**kwargs):
        path.write_text('partial or invalid output')
        return []
    monkeypatch.setattr(agents.reading_agent, 'create_reading_report', failed_generation)
    job = agents.start_report_regeneration(user_id='reader', report_id=report_id)['task']
    agents._finish_report_regeneration(job['task_id'])
    assert path.read_bytes() == original
    task = agents.get_reading_reports_task(job['task_id'])['task']
    assert task['status'] == 'failed' and task['failed_count'] == 1
    assert task['errors']
    backups = list((path.parents[1] / 'data' / 'report_backups').rglob('*.md'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    retry = agents.start_report_regeneration(user_id='reader', report_id=report_id)
    assert retry['already_running'] is False and retry['task']['task_id'] != job['task_id']


def test_regeneration_success_replaces_same_report_with_backup(existing_report, monkeypatch):
    path, report_id = existing_report
    original = path.read_bytes()
    def generate(**kwargs):
        request = kwargs['request_metadata']
        assert request['force_regenerate'] is True and request['require_llm'] is True
        assert request['regenerate_report_path'] == str(path)
        assert kwargs['send_to_feishu'] is False
        path.write_text('---\nuser_id: reader\ntitle: Original paper\nreport_version: new\n---\n中文新报告。\n')
        return [{'report_path': str(path), 'paper': kwargs['papers'][0]}]
    monkeypatch.setattr(agents.reading_agent, 'create_reading_report', generate)
    job = agents.start_report_regeneration(user_id='reader', report_id=report_id)['task']
    agents._finish_report_regeneration(job['task_id'])
    task = agents.get_reading_reports_task(job['task_id'])['task']
    assert task['status'] == 'completed' and task['completed_count'] == 1
    assert task['created_docs'][0]['report_id'] == report_id
    assert '中文新报告' in agents.get_report_content(report_id)['report']['markdown']
    assert next((path.parents[1] / 'data' / 'report_backups').rglob('*.md')).read_bytes() == original


def configure_generation(monkeypatch, tmp_path, llm_payload):
    reading = agents.reading_agent
    monkeypatch.setattr(reading, 'get_profile', lambda _: {'core_directions': {}})
    monkeypatch.setattr(reading, 'ensure_profile_schema', lambda p: p)
    def no_reuse(*args, **kwargs):
        raise AssertionError('Explicit regeneration must bypass all old report lookups')
    monkeypatch.setattr(reading, '_lookup_existing_pdf_report', no_reuse)
    monkeypatch.setattr(reading, 'get_existing_reading_reports_for_papers', no_reuse)
    monkeypatch.setattr(reading, '_enrich_paper_for_reading_report_compat', lambda p, **kw: (p, None, None))
    monkeypatch.setattr(reading, 'build_heuristic_report_payload', lambda *a, **kw: {'generation_provider': 'heuristic', 'analysis_source': 'pdf'})
    monkeypatch.setattr(reading, '_synthesize_report_with_llm', lambda *a, **kw: llm_payload)
    monkeypatch.setattr(reading, '_resolve_configured_dir', lambda *a, **kw: tmp_path)
    monkeypatch.setattr(reading, '_sync_obsidian_daily_note', lambda **kw: None)
    monkeypatch.setattr(reading, 'ingest_reading_report_to_wiki', lambda **kw: {})
    monkeypatch.setattr(reading, 'log_behavior', lambda **kw: None)
    monkeypatch.setattr(reading, '_annotate_tracking_links', lambda *a: None)
    return reading


def test_actual_generation_bypasses_pdf_and_paper_reuse_and_writes_selected_path(tmp_path, monkeypatch):
    reading = configure_generation(monkeypatch, tmp_path, {
        'generation_provider': 'chatgpt', 'generation_model': 'test', 'title_zh': '中文标题',
        'clean_abstract_summary': '中文摘要。', 'problem_analysis': '问题分析。',
        'solution_approach': '方法分析。', 'paper_summary': '论文总结。',
    })
    path = tmp_path / 'existing-original-name.md'
    path.write_text('Old report')
    docs = reading.create_reading_report(user_id='reader', paper_ids=[], papers=[{'id': 1, 'title': 'Original', 'abstract': 'Source'}], send_to_feishu=False,
        request_metadata={'force_regenerate': True, 'require_llm': True, 'regenerate_report_path': str(path),
                          'report_source_type': 'desktop_pdf_path', 'report_source_key': 'same-pdf', 'response_language': 'zh'})
    assert len(docs) == 1 and not docs[0].get('reused')
    assert Path(docs[0]['report_path']) == path
    assert '中文摘要。' in path.read_text() and '问题分析。' in path.read_text()
    assert not list(tmp_path.glob('*.tmp'))


def test_actual_generation_never_replaces_old_report_with_heuristic_fallback(tmp_path, monkeypatch):
    reading = configure_generation(monkeypatch, tmp_path, {'analysis_note': 'Model timed out'})
    path = tmp_path / 'old.md'
    path.write_text('Original report remains')
    docs = reading.create_reading_report(user_id='reader', paper_ids=[], papers=[{'id': 1, 'title': 'Original', 'abstract': 'Source'}], send_to_feishu=False,
        request_metadata={'force_regenerate': True, 'require_llm': True, 'regenerate_report_path': str(path)})
    assert docs == []
    assert path.read_text() == 'Original report remains'


def test_regeneration_preserves_stored_ranking_evidence(existing_report, test_db_path, sample_paper, monkeypatch):
    path, report_id = existing_report
    db = agents.db_ops
    monkeypatch.setattr(db, 'DB_PATH', test_db_path)
    paper_id = db.add_paper(sample_paper)
    db.log_behavior('reader', 'batch', paper_id, 'pushed', 'push', 'high_relevant', metadata={'score': .8, 'category': 'high_relevant'})
    path.write_text(path.read_text().replace('user_id: reader\n', f'user_id: reader\npaper_id: {paper_id}\n'))
    result = agents.start_report_regeneration(user_id='reader', report_id=report_id)
    paper = agents._READING_TASKS[result['task']['task_id']]['internal_docs'][0]['paper_raw']
    assert paper['score'] == .8 and paper['category'] == 'high_relevant'
    assert paper['abstract'] == sample_paper['abstract']


def test_actual_frontend_retry_posts_report_id_once_and_restores_button_on_error():
    import json
    import os
    import shutil
    import subprocess
    node = shutil.which('node') or os.environ.get('PAPERFLOW_NODE')
    if not node:
        pytest.skip('Node.js needed to run actual frontend functions')
    source = (Path(__file__).resolve().parents[1] / 'deployments/desktop/static/desktop.js').read_text()
    code = 'function updateRegenerateReportButton() {' + source.split('  function updateRegenerateReportButton() {', 1)[1].split('  async function loadReportContent(', 1)[0]
    script = r'''
const state={currentReport:{report_id:'report',user_id:'reader',can_regenerate:true}};
const elements={regenerateReportBtn:{},reportRegenerationStatus:{}};
const $=id=>elements[id]; const currentUser=()=> 'reader'; const responseLanguage=()=> 'zh';
const ensureLlmReadyForReading=async()=>true;
const openReport=async()=>{}; const showFeedbackToast=()=>{};
const requests=[]; let fail=false;
const api=async(route,options)=>{requests.push({route,body:JSON.parse(options.body)}); if(fail)throw Error('offline'); return {task:{task_id:'task',status:'running'}}};
const pollReadingTask=async()=>{state.currentReport.regeneration_task.status='completed'};
''' + code + r'''
(async()=>{
 await Promise.all([regenerateReport(),regenerateReport()]);
 const first={count:requests.length,disabled:elements.regenerateReportBtn.disabled};
 state.currentReport.regeneration_task=null; fail=true;
 try{await regenerateReport()}catch(e){}
 process.stdout.write(JSON.stringify({requests,first,disabled:elements.regenerateReportBtn.disabled,label:elements.regenerateReportBtn.textContent}));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data['first'] == {'count': 1, 'disabled': False}
    assert data['requests'][0] == {'route': '/api/reports/regenerate', 'body': {'user_id': 'reader', 'report_id': 'report', 'response_language': 'zh'}}
    assert data['disabled'] is False and data['label'] == '重新生成'

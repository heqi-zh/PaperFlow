from datetime import datetime, date
import importlib
from types import SimpleNamespace


journal = importlib.import_module('skills.journal-fetcher.scripts.fetch_journal')
conference = importlib.import_module('skills.openreview-fetcher.scripts.fetch_openreview')


def test_crossref_import_uses_online_date_and_preserves_identifiers(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 10, 28)
    monkeypatch.setattr(journal, 'datetime', Clock)
    monkeypatch.setattr(journal, 'query_crossref_works', lambda *a, **k: [
        {'title':['Robot planning'], 'DOI':'10.test/example', 'published-online':{'date-parts':[[2026,10,25]]},
         'published-print':{'date-parts':[[2027,1]]}, 'author':[{'given':'A','family':'Author'}]},
        {'title':['Old paper'], 'published':{'date-parts':[[2025,1,1]]}},
        {'title':['Undated paper']},
    ])
    papers = journal.fetch_journal_papers('RA-L', limit=5, days=7)
    assert [p['title'] for p in papers] == ['Robot planning']
    assert papers[0]['doi'] == '10.test/example'
    assert papers[0]['publish_date'] == '2026-10-25T00:00:00'
    assert papers[0]['authors'] == ['A Author']


def test_conference_fallback_rejects_other_venues(monkeypatch):
    monkeypatch.setattr(journal, 'query_crossref_works', lambda *a, **k: [
        {'title':['Graphics paper'], 'container-title':['ACM SIGGRAPH 2026 Conference Papers'], 'published':{'date-parts':[[2026,7,20]]}},
        {'title':['Asia paper'], 'container-title':['ACM SIGGRAPH Asia 2026 Conference Papers'], 'published':{'date-parts':[[2026,12,1]]}},
        {'title':['Unrelated'], 'container-title':['Unrelated proceedings'], 'published':{'date-parts':[[2026,7,20]]}},
    ])
    result = conference._search_crossref_conference_papers('siggraph',2026,10)
    assert [x['title'] for x in result] == ['Graphics paper']


def test_corl_fetch_uses_accepted_venue_without_submission_invitation(monkeypatch):
    calls=[]
    class Client:
        def get_notes(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(id='note',content={'title':{'value':'Robot paper'},'abstract':{'value':'abstract'},'authors':{'value':['Author']}},cdate=1770000000000)]
    monkeypatch.setattr(conference,'get_client',lambda:Client())
    result=conference.search_papers(conference='CoRL',year=2026,limit=1)
    assert calls == [{'content':{'venueid':'robot-learning.org/CoRL/2026/Conference'},'limit':1}]
    assert result[0]['title']=='Robot paper'


def test_annual_catalog_is_marked_and_scoped_to_requested_year():
    paper={'publish_date':'2026-01-01T00:00:00','publish_date_precision':'year'}
    assert conference._paper_in_date_range(paper,date(2026,10,1),date(2026,10,28))
    assert not conference._paper_in_date_range(paper,date(2025,1,1),date(2025,12,31))


def test_selected_catalogs_do_not_reintroduce_biology():
    from deployments.desktop.shared import agents
    choices=agents.source_options()
    assert not any(x['id'].startswith('q-bio') for x in choices['arxiv_categories'])
    assert {'cs.RO','cs.GR','cs.CV'} <= {x['id'] for x in choices['arxiv_categories']}
    assert {'ICRA','IROS','RSS','CoRL','SIGGRAPH','SIGGRAPH Asia'} <= {x['id'] for x in choices['conferences']}
    journals={x['id'] for x in choices['journals']}
    assert {'RA-L','T-RO','ACM TOG','Computer Graphics Forum'} <= journals
    assert not journals & {'Nature Biotechnology','Nature Methods','Cell','PNAS','Nature','Science'}
    assert not set(agents.daily_agent.load_default_journals()) & {'nature','cell','pnas','nature-biotech'}

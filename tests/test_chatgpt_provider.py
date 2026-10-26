"""Integration boundaries for PaperFlow's independent ChatGPT transport."""
import importlib

import pytest

from paperflow.providers import build_llm_provider
from paperflow.providers.chatgpt import ChatGPTLLM
import paperflow.providers.chatgpt as transport


def test_factory_uses_chatgpt_without_api_key(monkeypatch):
    monkeypatch.setenv('PAPERFLOW_LLM_PROVIDER', 'chatgpt')
    monkeypatch.setenv('PAPERFLOW_LLM_MODEL', 'account-model')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    provider = build_llm_provider()
    assert isinstance(provider, ChatGPTLLM)
    assert provider.model == 'account-model'


def test_generate_preserves_model_and_omits_unsupported_options(monkeypatch):
    calls = []
    def fake_rpc(op, **args):
        calls.append((op, args))
        return {'text': 'real transport result', 'model': 'resolved-model'}
    monkeypatch.setattr(transport, 'rpc', fake_rpc)
    result = ChatGPTLLM().generate('paper', system='rank', temperature=.7, max_tokens=12)
    assert calls == [('generate', {'model': 'auto', 'prompt': 'paper', 'system': 'rank'})]
    assert (result.provider, result.model, result.text) == ('chatgpt', 'resolved-model', 'real transport result')


def test_auth_error_does_not_fall_back_to_mock(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('reauth_required')
    monkeypatch.setattr(transport, 'rpc', fail)
    with pytest.raises(RuntimeError, match='reauth_required'):
        ChatGPTLLM().generate('paper')


def test_legacy_parser_uses_canonical_chatgpt_backend(monkeypatch):
    parser = importlib.import_module('agents.master-coordinator.scripts.llm_parser')
    monkeypatch.setenv('PAPERFLOW_LLM_PROVIDER', 'chatgpt')
    monkeypatch.setattr(transport, 'rpc', lambda *a, **k: {'text': '{"score": 0.8}', 'model': 'account-model'})
    result = parser._generate_json_with_configured_llm('Return JSON', 'paper', max_tokens=200)
    assert result == {'score': .8, 'generation_provider': 'chatgpt', 'generation_model': 'account-model'}


@pytest.mark.parametrize('headers,allowed', [
    ({'Host': '127.0.0.1:8766', 'Origin': 'http://127.0.0.1:8766'}, True),
    ({'Host': '127.0.0.1:8766', 'Origin': 'https://other.example'}, False),
    ({'Host': 'other.example:8766', 'Origin': 'http://other.example:8766'}, False),
])
def test_account_routes_only_allow_local_origin(headers, allowed):
    from deployments.desktop.server import PaperFlowGuiHandler
    class Request:
        def __init__(self):
            self.headers = headers
            self.status = None
        def _send_json(self, body, status):
            self.status = status
    request = Request()
    assert PaperFlowGuiHandler._allow_chatgpt_request(request) == allowed
    assert request.status == (None if allowed else 403)


def test_unknown_account_model_cannot_be_saved(monkeypatch):
    from deployments.desktop.server import _chatgpt_api
    monkeypatch.setattr(transport, 'rpc', lambda *a, **k: {'models': [{'slug': 'permitted'}]})
    with pytest.raises(ValueError, match='returned by the current'):
        _chatgpt_api('configure', {'model': 'invented-model'})

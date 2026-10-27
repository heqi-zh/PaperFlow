"""Profile embeddings must be comparable with the configured paper encoder."""
import importlib
import pytest

coldstart = importlib.import_module('agents.coldstart-agent.main')
embed = importlib.import_module('skills.embedding.scripts.embed')


def test_interests_use_configured_encoder_and_direction_weights(monkeypatch):
    class Encoder:
        def embed_batch(self, texts):
            return [[1., 0., 0.], [0., 1., 0.]]
    monkeypatch.setattr(embed, 'get_embedding_service', lambda: Encoder())
    # Weight changes must change the direction of the actual semantic vector.
    a = coldstart.generate_interest_vector({'first': 3, 'second': 4})
    b = coldstart.generate_interest_vector({'first': 4, 'second': 3})
    assert a == pytest.approx([.6, .8, 0.])
    assert b == pytest.approx([.8, .6, 0.])


def test_empty_interest_does_not_load_a_model(monkeypatch):
    def unexpected():
        raise AssertionError('Empty profile should not load the encoder')
    monkeypatch.setattr(embed, 'get_embedding_service', unexpected)
    assert coldstart.generate_interest_vector({}) == []


def test_editing_directions_replaces_stale_profile_vector(monkeypatch):
    from deployments.desktop.shared import agents
    profile = {'user_id': 'test', 'core_directions': {'old': 1}, 'interest_vector': [1., 0.]}
    saved = {}
    monkeypatch.setattr(agents.db_ops, 'get_profile', lambda user_id: profile)
    monkeypatch.setattr(agents.db_ops, 'update_profile', lambda user_id, value: saved.update(value))
    monkeypatch.setattr(coldstart, 'generate_interest_vector', lambda directions: [0., 1., 0.])
    agents._apply_manual_profile_updates('test', {'core_directions': {'new': .9}})
    assert saved['interest_vector'] == [0., 1., 0.]

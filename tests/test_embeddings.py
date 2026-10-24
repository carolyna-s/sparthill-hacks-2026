"""Free-text embeddings: refresh only calls the API for changed answers. The API is stubbed."""

import openai
import pytest

from app import embeddings
from app.extensions import db
from app.models import Profile, User

from .conftest import login


@pytest.fixture
def calls(app, monkeypatch):
    """Stub the OpenAI call; record each batch of texts sent."""
    sent = []

    def fake_embed(texts):
        sent.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]

    app.config["OPENAI_API_KEY"] = "test-key"
    monkeypatch.setattr(embeddings, "embed", fake_embed)
    return sent


def _profile(**text) -> Profile:
    p = db.session.query(User).filter_by(email="jordan.kim@example.org").one().profile
    p.interests, p.goals_other, p.looking_for = text.get("interests"), text.get("goals_other"), text.get("looking_for")
    p.text_embeddings = None
    return p


def test_refresh_embeds_only_new_or_changed_answers(calls):
    p = _profile(interests="robots", looking_for="mock interviews")
    assert embeddings.refresh(p)
    assert calls == [["robots", "mock interviews"]]  # one call, blanks skipped
    assert set(embeddings.vectors(p)) == {"interests", "looking_for"}

    assert embeddings.refresh(p)
    assert len(calls) == 1  # nothing changed: no call

    p.looking_for, p.interests = "resume review", ""
    assert embeddings.refresh(p)
    assert calls[-1] == ["resume review"]
    assert set(embeddings.vectors(p)) == {"looking_for"}  # cleared answer's vector dropped


def test_refresh_without_key_or_on_error_leaves_no_stale_vector(app, calls, monkeypatch):
    p = _profile(looking_for="mock interviews")
    embeddings.refresh(p)

    def boom(texts):
        raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(embeddings, "embed", boom)
    p.looking_for = "something else"
    assert not embeddings.refresh(p)
    assert embeddings.vectors(p) == {}  # the old vector no longer matches the text

    app.config["OPENAI_API_KEY"] = ""
    assert not embeddings.refresh(p)


def test_vectors_from_another_model_are_ignored_and_redone(app, calls):
    p = _profile(interests="robots")
    embeddings.refresh(p)
    app.config["OPENAI_EMBEDDING_MODEL"] = "text-embedding-3-large"
    assert embeddings.vectors(p) == {}
    embeddings.refresh(p)
    assert calls == [["robots"], ["robots"]]


def test_saving_the_text_step_embeds_answers(client, calls):
    login(client, "jordan.kim@example.org")
    client.post("/profile/4", data={"looking_for": "Interview practice", "interests": "robotics"})
    p = db.session.query(User).filter_by(email="jordan.kim@example.org").one().profile
    assert set(embeddings.vectors(p)) == {"interests", "looking_for"}


def test_backfill_embeds_seeded_profiles(calls):
    done, failed = embeddings.backfill()
    assert failed == 0 and done == db.session.query(Profile).filter(Profile.text_embeddings.isnot(None)).count() > 0

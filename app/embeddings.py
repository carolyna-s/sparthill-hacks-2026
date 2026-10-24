"""Embeddings of the free-text answers and the industry, for the semantic parts of the match
score.

Each text box, and the industry name, is embedded on its own with OpenAI
(`OPENAI_EMBEDDING_MODEL` at EMBEDDING_DIM) and stored in `profile.text_embeddings` with a hash
of the text it came from:

    {"model": "text-embedding-3-small:384",
     "fields": {"looking_for": {"hash": "9f2c...", "vector": [...]}, "industry": {...}, ...}}

The industry is embedded as "Industry: <name>": bare names are too short to embed well (bare
"Software Development" was as close to "Wine and Spirits" as to "Artificial Intelligence");
the label pulls near-synonyms well clear of unrelated industries. See INDUSTRY_RANGE in
app/matching.py for what it still can't tell apart.

`refresh` only calls the API for answers that are new or changed, and drops vectors for
answers that were cleared or changed, so a stored vector always matches its text. Without
OPENAI_API_KEY (or if the API fails) nothing new is embedded, and matching leaves the
semantic part out for pairs it can't compare. `flask embed` fills in what's missing.
"""

from __future__ import annotations

import hashlib

from flask import current_app

from .extensions import db
from .models import Profile
from .types import EMBEDDING_DIM

# Compared mentee field <-> the same mentor field: what the mentee is looking for vs what the
# mentor hopes to offer, interests vs interests, other goals vs goals they can help with.
TEXT_FIELDS = ("interests", "goals_other", "looking_for")
EMBEDDED_FIELDS = TEXT_FIELDS + ("industry",)  # industry is scored on its own, not with the text
PREFIXES = {"industry": "Industry: "}
MAX_CHARS = 20_000  # far beyond any real answer; keeps a pasted essay under the model's limit


def model_tag() -> str:
    return f"{current_app.config['OPENAI_EMBEDDING_MODEL']}:{EMBEDDING_DIM}"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _input(p: Profile, f: str) -> str:
    """What gets embedded for field `f`, or "" if it's blank."""
    text = (getattr(p, f) or "").strip()
    return PREFIXES.get(f, "") + text if text else ""


def embed(texts: list[str]) -> list[list[float]]:
    """One API call for all `texts`, vectors in the same order. Raises openai.OpenAIError."""
    from openai import OpenAI

    client = OpenAI(api_key=current_app.config["OPENAI_API_KEY"], timeout=10.0, max_retries=1)
    resp = client.embeddings.create(model=current_app.config["OPENAI_EMBEDDING_MODEL"],
                                    input=[t[:MAX_CHARS] for t in texts], dimensions=EMBEDDING_DIM)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


def vectors(p: Profile) -> dict[str, list[float]]:
    """The profile's current vectors by field; empty if they came from a different model."""
    data = p.text_embeddings or {}
    if data.get("model") != model_tag():
        return {}
    return {f: v["vector"] for f, v in data.get("fields", {}).items()}


def refresh(p: Profile) -> bool:
    """Bring `p.text_embeddings` up to date with its answers. False if some answer is left
    without a vector (no API key, or the call failed); the caller commits."""
    import openai

    data = p.text_embeddings or {}
    stored = data.get("fields", {}) if data.get("model") == model_tag() else {}
    texts = {f: _input(p, f) for f in EMBEDDED_FIELDS}
    fields = {f: v for f, v in stored.items() if texts.get(f) and v["hash"] == _hash(texts[f])}
    todo = [f for f in EMBEDDED_FIELDS if texts[f] and f not in fields]

    ok = not todo
    if todo and current_app.config["OPENAI_API_KEY"]:
        try:
            for f, vec in zip(todo, embed([texts[f] for f in todo])):
                fields[f] = {"hash": _hash(texts[f]), "vector": vec}
            ok = True
        except openai.OpenAIError as e:
            current_app.logger.warning("embedding profile %s failed: %s", p.id, e)
    p.text_embeddings = {"model": model_tag(), "fields": fields} if fields else None
    return ok


def backfill() -> tuple[int, int]:
    """Refresh every profile with a text answer or an industry. Returns (up to date, still
    missing vectors)."""
    has_text = db.or_(*(db.func.length(db.func.trim(getattr(Profile, f))) > 0 for f in EMBEDDED_FIELDS))
    done = failed = 0
    for p in db.session.query(Profile).filter(has_text):
        if refresh(p):
            done += 1
        else:
            failed += 1
        db.session.commit()
    return done, failed

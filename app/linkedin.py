"""LinkedIn import: turn a "Save to PDF" profile export into suggested profile fields.

No scraping (LinkedIn's terms forbid it, see docs/PLAN.md §6.2). The user downloads their own
profile as a PDF and uploads it. Two passes, as in PLAN.md §6.1:

- LLM pass (when ANTHROPIC_API_KEY is set): Claude reads the PDF and returns structured JSON,
  with every tag constrained to the taxonomy so it maps straight onto the form.
- Keyword pass (fallback, free, deterministic): a taxonomy value found in the text is suggested.

Either way the result only pre-fills the form; nothing is saved until the user confirms.
"""

from __future__ import annotations

import base64
import io
import json
import logging

from flask import current_app

from .taxonomy import INDUSTRIES, TAXONOMY

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"

# Tags a profile export can tell us about. Availability can't come from LinkedIn.
SUGGESTABLE = [dim for dim in TAXONOMY if dim != "availability"]

PROMPT = """This is a LinkedIn profile exported to PDF by a {role} joining a mentorship program.
Extract it into the schema. For each tag list, pick only values the profile clearly supports;
leave a list empty rather than guess. {role_note}
`summary` is a 2-4 sentence third-person overview of their background and direction, for
matching them with a {other}."""

ROLE_NOTES = {
    "mentor": ("`industry` is the industry they work in. Tags describe what the mentor offers: "
               "skills they can teach, goals they can help with, and their educational path."),
    "mentee": ("`industry` is the industry they're interested in. Tags describe what the mentee "
               "wants: skills to build, goals, and their educational path."),
}


def _schema() -> dict:
    tag_lists = {dim: {"type": "array", "items": {"type": "string", "enum": TAXONOMY[dim]}}
                 for dim in SUGGESTABLE}
    experience = {
        "type": "object",
        "properties": {"company": {"type": "string"}, "title": {"type": "string"},
                       "start": {"type": "string"}, "end": {"type": "string"},
                       "description": {"type": "string"}},
        "required": ["company", "title", "start", "end", "description"],
        "additionalProperties": False,
    }
    education = {
        "type": "object",
        "properties": {"school": {"type": "string"}, "degree": {"type": "string"},
                       "field": {"type": "string"}},
        "required": ["school", "degree", "field"],
        "additionalProperties": False,
    }
    props = {
        "headline": {"type": "string"},
        "organization": {"type": "string", "description": "current employer or school"},
        "school": {"type": "string", "description": "most recent school attended"},
        "industry": {"type": "string",
                     "description": "a LinkedIn industry name, e.g. " + ", ".join(INDUSTRIES[:5])
                                    + "; empty if unclear"},
        "summary": {"type": "string"},
        "years_experience": {"type": "integer"},
        "experience": {"type": "array", "items": experience},
        "education": {"type": "array", "items": education},
        "activities": {"type": "array", "items": {"type": "string"},
                       "description": "clubs, societies, volunteering"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "object", "properties": tag_lists, "required": SUGGESTABLE,
                 "additionalProperties": False},
    }
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def keyword_pass(text: str) -> dict:
    """Suggest every taxonomy value, and the first industry, that appears verbatim in the text."""
    lowered = text.lower()
    return {"tags": {dim: [v for v in TAXONOMY[dim] if v.lower() in lowered] for dim in SUGGESTABLE},
            "industry": next((i for i in INDUSTRIES if i.lower() in lowered), "")}


def llm_pass(data: bytes, role: str) -> dict:
    import anthropic

    other = "mentee" if role == "mentor" else "mentor"
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}},
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(data).decode()}},
            {"type": "text", "text": PROMPT.format(role=role, role_note=ROLE_NOTES[role], other=other)},
        ]}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"LinkedIn parse stopped: {response.stop_reason}")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def parse(data: bytes, role: str) -> dict:
    """Parsed profile: {headline, organization, school, industry, summary, ..., tags, source}.

    Falls back to the keyword pass when there's no API key or the call fails, so an upload
    always gives the user something to confirm.
    """
    if current_app.config["ANTHROPIC_API_KEY"]:
        try:
            parsed = llm_pass(data, role)
            parsed["source"] = "llm"
        except Exception:
            log.exception("LinkedIn LLM pass failed; using keyword pass")
        else:
            return _clean(parsed)
    return _clean({**keyword_pass(pdf_text(data)), "source": "keywords"})


def _clean(parsed: dict) -> dict:
    tags = parsed.get("tags") or {}
    parsed["tags"] = {dim: [t for t in tags.get(dim, []) if t in TAXONOMY[dim]] for dim in SUGGESTABLE}
    parsed["industry"] = " ".join((parsed.get("industry") or "").split())[:120]
    return parsed

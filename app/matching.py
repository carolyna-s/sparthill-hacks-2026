"""Score-based mentor ranking.

Hard filters drop a pair outright: they must share at least one availability slot and one
language. Blank languages count as English. A side with no availability yet (older profiles)
isn't filtered on it.

Every remaining pair gets a weighted soft-filter score, each dimension 0-1:

    score = 100 * sum(weight[d] * sim[d]) / sum(weight)

- coverage dimensions (industry, skills, goals): share of what the mentee asked for that the
  mentor covers. Coverage (not Jaccard) is used on purpose: a mentor with many tags shouldn't
  be penalized for breadth.
- preference dimensions (career outlook, seniority, style, company type, education path):
  1 if the mentor has any of the values the mentee picked, else 0.
- alumni: 1 if the mentee asked for a same-school mentor and the schools match.

A dimension the mentee left empty (or alumni when not requested) counts as fully covered, so
it doesn't drag every score down. Mentors at capacity are excluded.

The scoring functions take plain dicts so they're trivial to test and tune; the DB helpers
at the bottom adapt Profile rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func

from .extensions import db
from .models import Application, Match, Profile, User

HARD_FILTERS = ("availability", "languages")
HARD_FILTER_DEFAULTS = {"languages": ["English"]}  # what a blank answer means
COVERAGE = ("career_interests", "development_areas", "goals")
PREFERENCE = ("career_outlook", "seniority", "mentoring_style", "company_types", "education_paths")

WEIGHTS = {"career_interests": 0.20, "development_areas": 0.15, "goals": 0.15, "career_outlook": 0.10,
           "seniority": 0.10, "mentoring_style": 0.10, "company_types": 0.08, "education_paths": 0.07,
           "alumni": 0.05}

FIELDS = HARD_FILTERS + COVERAGE + PREFERENCE + ("school", "prefers_alumni")


@dataclass
class Candidate:
    mentor_id: int
    score: float
    breakdown: dict = field(default_factory=dict)


def hard_filter_overlap(mentee: dict, mentor: dict) -> dict[str, list] | None:
    """Shared values per hard filter, or None if the pair fails one."""
    overlap = {}
    for dim in HARD_FILTERS:
        default = HARD_FILTER_DEFAULTS.get(dim, [])
        a, b = set(mentee.get(dim) or default), set(mentor.get(dim) or default)
        shared = a & b
        if a and b and not shared:
            return None
        overlap[dim] = sorted(shared)
    return overlap


def _same_school(mentee: dict, mentor: dict) -> bool:
    a, b = (mentee.get("school") or "").strip().lower(), (mentor.get("school") or "").strip().lower()
    return bool(a) and a == b


def score_pair(mentee: dict, mentor: dict, weights: dict = WEIGHTS) -> tuple[float, dict]:
    total, breakdown = 0.0, {}
    for dim, w in weights.items():
        if dim == "alumni":
            wanted = mentee.get("prefers_alumni")
            shared = [mentor["school"]] if wanted and _same_school(mentee, mentor) else []
            sim = (1.0 if shared else 0.0) if wanted else 1.0
        else:
            wanted = set(mentee.get(dim) or [])
            shared = sorted(wanted & set(mentor.get(dim) or []))
            if not wanted:
                sim = 1.0
            elif dim in PREFERENCE:
                sim = 1.0 if shared else 0.0
            else:
                sim = len(shared) / len(wanted)
        total += w * sim
        breakdown[dim] = {"coverage": round(sim, 3), "shared": shared, "weight": w}
    return round(100 * total / sum(weights.values()), 1), breakdown


def rank_mentors(mentee: dict, mentors: dict[int, dict], open_slots: dict[int, int],
                 limit: int | None = None) -> list[Candidate]:
    """mentors: {mentor_id: tags}, open_slots: {mentor_id: remaining capacity}."""
    ranked = []
    for mentor_id, tags in mentors.items():
        if open_slots.get(mentor_id, 0) <= 0:
            continue
        overlap = hard_filter_overlap(mentee, tags)
        if overlap is None:
            continue
        score, breakdown = score_pair(mentee, tags)
        breakdown["filters"] = overlap
        ranked.append(Candidate(mentor_id, score, breakdown))
    ranked.sort(key=lambda c: (-c.score, c.mentor_id))
    return ranked[:limit] if limit else ranked


def assign(mentees: dict[int, dict], mentors: dict[int, dict],
           open_slots: dict[int, int]) -> dict[int, Candidate]:
    """Propose one mentor per mentee: best-scoring pairs first, respecting capacity.

    Greedy over all pairs is simple and explainable to staff; swap in a min-cost-flow
    solver later if globally optimal assignments matter.
    """
    slots = dict(open_slots)
    pairs = []
    for mentee_id, tags in mentees.items():
        for c in rank_mentors(tags, mentors, slots):
            pairs.append((mentee_id, c))
    pairs.sort(key=lambda p: (-p[1].score, p[0], p[1].mentor_id))

    result: dict[int, Candidate] = {}
    for mentee_id, c in pairs:
        if mentee_id in result or slots.get(c.mentor_id, 0) <= 0:
            continue
        result[mentee_id] = c
        slots[c.mentor_id] -= 1
    return result


# --- DB adapters -------------------------------------------------------------

def _tags(p: Profile) -> dict:
    return {f: getattr(p, f) for f in FIELDS}


def accepted_profiles(role: str) -> dict[int, dict]:
    rows = (db.session.query(Profile)
            .join(User, User.id == Profile.user_id)
            .join(Application, Application.user_id == User.id)
            .filter(User.role == role, Application.status == "accepted")
            .all())
    return {p.user_id: _tags(p) for p in rows}


def open_slots() -> dict[int, int]:
    """Remaining capacity per accepted mentor, counting approved and proposed matches."""
    taken = dict(db.session.query(Match.mentor_id, func.count(Match.id))
                 .filter(Match.status.in_(("approved", "proposed")))
                 .group_by(Match.mentor_id).all())
    caps = dict(db.session.query(Profile.user_id, Profile.capacity)
                .filter(Profile.user_id.in_(accepted_profiles("mentor").keys())).all())
    return {mid: cap - taken.get(mid, 0) for mid, cap in caps.items()}


def unmatched_mentee_ids() -> set[int]:
    matched = {m for (m,) in db.session.query(Match.mentee_id)
               .filter(Match.status.in_(("approved", "proposed")))}
    return set(accepted_profiles("mentee")) - matched


def ranking_for(mentee_id: int, limit: int = 5) -> list[Candidate]:
    profile = db.session.query(Profile).filter_by(user_id=mentee_id).one()
    return rank_mentors(_tags(profile), accepted_profiles("mentor"), open_slots(), limit)


def propose_all() -> list[Match]:
    """Create `proposed` matches for every unmatched accepted mentee."""
    mentees = {k: v for k, v in accepted_profiles("mentee").items() if k in unmatched_mentee_ids()}
    created = []
    for mentee_id, c in assign(mentees, accepted_profiles("mentor"), open_slots()).items():
        m = Match(mentee_id=mentee_id, mentor_id=c.mentor_id, score=c.score, score_breakdown=c.breakdown)
        db.session.add(m)
        created.append(m)
    db.session.commit()
    return created

"""Score-based mentor ranking.

A mentor's score for a mentee is how much of what the mentee asked for the mentor covers,
per dimension, weighted:

    score = 100 * sum(weight[d] * |mentee[d] & mentor[d]| / |mentee[d]|)

Coverage (not Jaccard) is used on purpose: a mentor with many tags shouldn't be penalized
for breadth. A dimension the mentee left empty counts as fully covered, so it doesn't drag
every score down. Mentors at capacity are excluded.

The scoring functions take plain dicts so they're trivial to test and tune; the DB helpers
at the bottom adapt Profile rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func

from .extensions import db
from .models import Application, Match, Profile, User

WEIGHTS = {"career_interests": 0.4, "goals": 0.3, "development_areas": 0.3}


@dataclass
class Candidate:
    mentor_id: int
    score: float
    breakdown: dict = field(default_factory=dict)


def score_pair(mentee: dict, mentor: dict, weights: dict = WEIGHTS) -> tuple[float, dict]:
    total, breakdown = 0.0, {}
    for dim, w in weights.items():
        wanted = set(mentee.get(dim) or [])
        offered = set(mentor.get(dim) or [])
        shared = wanted & offered
        coverage = len(shared) / len(wanted) if wanted else 1.0
        total += w * coverage
        breakdown[dim] = {"coverage": round(coverage, 3), "shared": sorted(shared), "weight": w}
    return round(100 * total, 1), breakdown


def rank_mentors(mentee: dict, mentors: dict[int, dict], open_slots: dict[int, int],
                 limit: int | None = None) -> list[Candidate]:
    """mentors: {mentor_id: tags}, open_slots: {mentor_id: remaining capacity}."""
    ranked = []
    for mentor_id, tags in mentors.items():
        if open_slots.get(mentor_id, 0) <= 0:
            continue
        score, breakdown = score_pair(mentee, tags)
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
    return {dim: getattr(p, dim) for dim in WEIGHTS}


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

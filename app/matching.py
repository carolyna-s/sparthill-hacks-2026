"""Score-based mentor ranking.

Hard filters drop a pair outright: they must share at least one availability slot and one
language. Blank languages count as English. A side with no availability yet (older profiles)
isn't filtered on it.

Every remaining pair gets a weighted soft-filter score, each dimension 0-1:

    score = 100 * sum(weight[d] * sim[d]) / sum(weight)

- industry: 1 if the same (ignoring case), else 0.
- coverage dimensions (skills, goals): share of what the mentee asked for that the mentor
  covers. Coverage (not Jaccard) is used on purpose: a mentor with many tags shouldn't be
  penalized for breadth.
- preference dimensions (education path): 1 if the mentor has any of the mentee's picks.
- alumni: 1 if the mentee asked for a same-school mentor and the schools match.
- text: how close the free-text answers are in meaning (app/embeddings.py), averaged over
  the text boxes both sides filled in; cosine similarity rescaled from SEMANTIC_RANGE to 0-1.

A dimension the mentee left empty (or alumni when not requested) counts as fully covered, so
it doesn't drag every score down. Text is different: a pair with no answers to compare (blank,
or not embedded yet) leaves it out of the score entirely, weight included.

Matching is one-to-one: each mentor takes one mentee. `assign` turns the scores into
proposals with the Hungarian algorithm (the assignment with the highest total score). Each run
covers only the pool: mentees and mentors with no approved or pending match. Every mentee is
matched while free mentors last; a pair that fails a hard filter is used only when nothing
compatible is left, and is flagged for staff. Pairs staff rejected (match_exclusion) are
never proposed again.

The scoring functions take plain dicts so they're trivial to test and tune; the DB helpers
at the bottom adapt Profile rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import embeddings
from .extensions import db
from .models import Application, Match, MatchExclusion, Profile, User

HARD_FILTERS = ("availability", "languages")
HARD_FILTER_DEFAULTS = {"languages": ["English"]}  # what a blank answer means
COVERAGE = ("development_areas", "goals")
PREFERENCE = ("education_paths",)

WEIGHTS = {
    "industry": 0.28,
    "development_areas": 0.20,
    "goals": 0.16,
    "text": 0.20,
    "education_paths": 0.08,
    "alumni": 0.08
    }

# Cosine similarities between OpenAI embeddings of short answers rarely go below ~0.2 even for
# unrelated text, or above ~0.7 for close paraphrases; stretch that band to 0-1. Tune once
# there are real answers to look at.
SEMANTIC_RANGE = (0.2, 0.7)

FIELDS = HARD_FILTERS + COVERAGE + PREFERENCE + ("industry", "school", "prefers_alumni")


@dataclass
class Candidate:
    mentor_id: int
    score: float
    breakdown: dict = field(default_factory=dict)


def hard_filters(mentee: dict, mentor: dict) -> tuple[dict[str, list], list[str]]:
    """Shared values per hard filter, and the filters the pair shares nothing on."""
    overlap, failed = {}, []
    for dim in HARD_FILTERS:
        default = HARD_FILTER_DEFAULTS.get(dim, [])
        a, b = set(mentee.get(dim) or default), set(mentor.get(dim) or default)
        shared = a & b
        if a and b and not shared:
            failed.append(dim)
        overlap[dim] = sorted(shared)
    return overlap, failed


def hard_filter_overlap(mentee: dict, mentor: dict) -> dict[str, list] | None:
    """Shared values per hard filter, or None if the pair fails one."""
    overlap, failed = hard_filters(mentee, mentor)
    return None if failed else overlap


def _same(mentee: dict, mentor: dict, key: str) -> bool:
    a, b = (mentee.get(key) or "").strip().lower(), (mentor.get(key) or "").strip().lower()
    return bool(a) and a == b


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return dot / norm if norm else 0.0


def text_similarity(mentee: dict, mentor: dict) -> dict[str, float]:
    """0-1 similarity per text box both sides have a vector for."""
    a, b = mentee.get("text_vectors") or {}, mentor.get("text_vectors") or {}
    lo, hi = SEMANTIC_RANGE
    return {f: min(1.0, max(0.0, (_cosine(a[f], b[f]) - lo) / (hi - lo)))
            for f in embeddings.TEXT_FIELDS if f in a and f in b}


def score_pair(mentee: dict, mentor: dict, weights: dict = WEIGHTS) -> tuple[float, dict]:
    total, used, breakdown = 0.0, 0.0, {}
    for dim, w in weights.items():
        if dim == "text":
            sims = text_similarity(mentee, mentor)
            if not sims:
                continue  # nothing to compare: leave text out of this pair's score
            sim = sum(sims.values()) / len(sims)
            shared = [f"{f.replace('_', ' ')} {round(100 * s)}%" for f, s in sims.items()]
        elif dim == "industry":
            wanted = (mentee.get("industry") or "").strip()
            shared = [mentor["industry"]] if _same(mentee, mentor, "industry") else []
            sim = (1.0 if shared else 0.0) if wanted else 1.0
        elif dim == "alumni":
            wanted = mentee.get("prefers_alumni")
            shared = [mentor["school"]] if wanted and _same(mentee, mentor, "school") else []
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
        used += w
        breakdown[dim] = {"coverage": round(sim, 3), "shared": shared, "weight": w}
    return round(100 * total / used, 1), breakdown


def rank_mentors(mentee: dict, mentors: dict[int, dict], open_slots: dict[int, int],
                 limit: int | None = None, excluded: set[int] = frozenset()) -> list[Candidate]:
    """Compatible mentors (sharing a time slot and language), best first.
    mentors: {mentor_id: tags}, open_slots: {mentor_id: 1 if free, else 0},
    excluded: mentor ids staff rejected for this mentee."""
    ranked = []
    for mentor_id, tags in mentors.items():
        if mentor_id in excluded or open_slots.get(mentor_id, 0) <= 0:
            continue
        overlap = hard_filter_overlap(mentee, tags)
        if overlap is None:
            continue
        score, breakdown = score_pair(mentee, tags)
        breakdown["filters"] = overlap
        ranked.append(Candidate(mentor_id, score, breakdown))
    ranked.sort(key=lambda c: (-c.score, c.mentor_id))
    return ranked[:limit] if limit else ranked


FORBIDDEN = -1e12  # can't be assigned: staff rejected the pair
MISMATCH = -1e6  # fails a hard filter: used only when no compatible mentor is left


def assign(mentees: dict[int, dict], mentors: dict[int, dict],
           excluded: set[tuple[int, int]] = frozenset()) -> dict[int, Candidate]:
    """One-to-one matching with the Hungarian algorithm: the assignment with the highest
    total score across everyone, not just the best pair first.

    mentors: the free mentors, each taking one mentee. excluded: (mentee_id, mentor_id) pairs
    never to propose. Every mentee gets a mentor while free mentors last. The penalties order
    the solver's goals: never a rejected pair, then as few pairs failing a hard filter as
    possible, then the highest total score. A pair that fails a hard filter is still matched
    when nothing else is left, with breakdown["filters_failed"] naming what they don't share.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    rows, cols = sorted(mentees), sorted(mentors)
    if not rows or not cols:
        return {}
    weight = np.full((len(rows), len(cols)), FORBIDDEN)
    pairs: dict[tuple[int, int], Candidate] = {}
    for i, me in enumerate(rows):
        for j, mt in enumerate(cols):
            if (me, mt) in excluded:
                continue
            overlap, failed = hard_filters(mentees[me], mentors[mt])
            score, breakdown = score_pair(mentees[me], mentors[mt])
            breakdown["filters"] = overlap
            if failed:
                breakdown["filters_failed"] = failed
            pairs[i, j] = Candidate(mt, score, breakdown)
            weight[i, j] = score + (MISMATCH if failed else 0)
    picked = zip(*linear_sum_assignment(weight, maximize=True))
    return {rows[i]: pairs[i, j] for i, j in picked if (i, j) in pairs}


# --- DB adapters -------------------------------------------------------------

def _tags(p: Profile) -> dict:
    return {**{f: getattr(p, f) for f in FIELDS}, "text_vectors": embeddings.vectors(p)}


def accepted_profiles(role: str) -> dict[int, dict]:
    rows = (db.session.query(Profile)
            .join(User, User.id == Profile.user_id)
            .join(Application, Application.user_id == User.id)
            .filter(User.role == role, Application.status == "accepted")
            .all())
    return {p.user_id: _tags(p) for p in rows}


def open_slots() -> dict[int, int]:
    """1 for each accepted mentor with no approved or pending match, else 0 (one-to-one)."""
    taken = {m for (m,) in db.session.query(Match.mentor_id)
             .filter(Match.status.in_(("approved", "proposed")))}
    return {mid: int(mid not in taken) for mid in accepted_profiles("mentor")}


def unmatched_mentee_ids() -> set[int]:
    matched = {m for (m,) in db.session.query(Match.mentee_id)
               .filter(Match.status.in_(("approved", "proposed")))}
    return set(accepted_profiles("mentee")) - matched


def excluded_pairs() -> set[tuple[int, int]]:
    """(mentee_id, mentor_id) pairs staff rejected."""
    return {(me, mt) for me, mt in db.session.query(MatchExclusion.mentee_id, MatchExclusion.mentor_id)}


def ranking_for(mentee_id: int, limit: int = 5) -> list[Candidate]:
    profile = db.session.query(Profile).filter_by(user_id=mentee_id).one()
    excluded = {mt for me, mt in excluded_pairs() if me == mentee_id}
    return rank_mentors(_tags(profile), accepted_profiles("mentor"), open_slots(), limit, excluded)


def rematch_round(mentee_id: int) -> int:
    """1 for a mentee's first proposal; one more for each proposal staff rejected."""
    return 1 + db.session.query(Match).filter_by(mentee_id=mentee_id, status="rejected").count()


def propose_all() -> list[Match]:
    """Run matching on the pool and create `proposed` matches.

    The pool is every accepted mentee and mentor without an approved or pending match (never
    matched, or their proposal was rejected). Approved matches are out of it for good;
    rejected pairs are never proposed again.
    """
    mentees = {k: v for k, v in accepted_profiles("mentee").items() if k in unmatched_mentee_ids()}
    free = open_slots()
    mentors = {k: v for k, v in accepted_profiles("mentor").items() if free.get(k)}
    created = []
    for mentee_id, c in assign(mentees, mentors, excluded_pairs()).items():
        m = Match(mentee_id=mentee_id, mentor_id=c.mentor_id, score=c.score, score_breakdown=c.breakdown,
                  rematch_round=rematch_round(mentee_id))
        db.session.add(m)
        created.append(m)
    db.session.commit()
    return created

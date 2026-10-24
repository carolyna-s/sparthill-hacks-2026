"""Score-based mentor ranking.

The hard filter drops a pair outright: they must share at least one availability slot. A side
with no availability yet (older profiles) isn't filtered on it.

Every remaining pair gets a weighted soft-filter score, each dimension 0-1:

    score = 100 * sum(weight[d] * sim[d]) / sum(weight)

- industry: 1 if the same (ignoring case). Otherwise partial credit for a related industry,
  the higher of: GROUP_CREDIT when both are in the same sector (taxonomy.INDUSTRY_GROUPS:
  Software Development vs Artificial Intelligence), and the cosine similarity of the embedded
  names rescaled from INDUSTRY_RANGE (Banking vs Financial Services ~0.75, which beats the
  sector credit). 0 for unrelated industries.
- coverage dimensions (skills, goals): share of what the mentee asked for that the mentor
  covers. Coverage (not Jaccard) is used on purpose: a mentor with many tags shouldn't be
  penalized for breadth.
- preference dimensions (education path): 1 if the mentor has any of the mentee's picks.
- alumni: 1 if the mentee asked for a same-school mentor and the schools match.
- text: how close the free-text answers are in meaning (app/embeddings.py), averaged over
  the text boxes both sides filled in; cosine similarity rescaled from SEMANTIC_RANGE to 0-1.
- languages: a bonus only. Everyone is assumed to get by in English, so sharing another
  language counts 1; sharing none (or only English) leaves it out of the score.

A dimension the mentee left blank (industry, skills, goals, education path) scores 0: no
answer is no evidence of fit. A mentee who picked "Open to Any" (skills) or "Undecided"
(goals, education path) gets NEUTRAL_CREDIT instead. Specific picks next to it still count,
whichever is higher. Alumni when not requested counts as fully covered: unchecked is an
answer ("no preference"), not a blank. Text and languages are different: a pair with nothing to
compare (no text embedded, no shared second language) leaves them out entirely, weight
included, so they can only raise a score.

Matching is one-to-one: each mentor takes one mentee. `assign` turns the scores into
proposals with the Hungarian algorithm (the assignment with the highest total score). Each run
covers only the pool: mentees and mentors with no approved or pending match. Every mentee is
matched while free mentors last; a pair that fails a hard filter is used only when nothing
compatible is left, and is flagged for staff: its score is None (they can't actually meet, so
a number would only inflate averages), with the would-be score kept as
breakdown["fit_if_compatible"]. Flagged pairs head the staff queue. Pairs staff rejected (match_exclusion) are
never proposed again, and neither is a pair whose match was ended or withdrawn; reopening the
match is the way back. Deactivated accounts (user.is_active) are left out of the pool.

The scoring functions take plain dicts so they're trivial to test and tune; the DB helpers
at the bottom adapt Profile rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import embeddings
from .extensions import db
from .models import Application, Match, MatchExclusion, MatchOverrideRequest, Profile, User
from .taxonomy import BASE_LANGUAGE, INDUSTRY_GROUPS, OPEN_TO_ANY, UNDECIDED

MENTEES_PER_MENTOR = 1  # one-to-one mentorship

HARD_FILTERS = ("availability",)
COVERAGE = ("development_areas", "goals")
PREFERENCE = ("education_paths",)
# The mentee-only "no preference" tag per dimension, and the credit it earns (0.3-0.4 of the
# dimension's weight was asked for).
NEUTRAL = {"development_areas": OPEN_TO_ANY, "goals": UNDECIDED, "education_paths": UNDECIDED}
NEUTRAL_CREDIT = 0.35

WEIGHTS = {
    "industry": 0.28,
    "development_areas": 0.20,
    "goals": 0.16,
    "text": 0.20,
    "education_paths": 0.08,
    "alumni": 0.08,
    "languages": 0.10,  # bonus: counted only when the pair shares a non-English language
    }

# Cosine similarities between OpenAI embeddings of short answers rarely go below ~0.2 even for
# unrelated text, or above ~0.7 for close paraphrases; stretch that band to 0-1. Tune once
# there are real answers to look at.
SEMANTIC_RANGE = (0.2, 0.7)
# Same idea for "Industry: <name>" embeddings, measured over every pair in the taxonomy: the
# median pair is ~0.50, near-synonyms ~0.8 (Banking ~ Financial Services 0.79). The floor is
# high on purpose: names alone don't separate loosely related industries from unrelated ones
# (Banking ~ Software Development 0.64 beats Software Development ~ AI 0.59), so only clearly
# close industries get credit; 10% of pairs get any.
INDUSTRY_RANGE = (0.60, 0.85)
# Same sector, different industry: enough to beat loosely related embeddings, well short of
# the same industry. The embedding catches near-synonyms across sectors and typed industries.
GROUP_CREDIT = 0.6
SECTORS = {}  # lowercased industry -> its sectors
for _sector, _industries in INDUSTRY_GROUPS.items():
    for _industry in _industries:
        SECTORS.setdefault(_industry.lower(), set()).add(_sector)

FIELDS = HARD_FILTERS + COVERAGE + PREFERENCE + ("languages", "industry", "school", "prefers_alumni")


@dataclass
class Candidate:
    mentor_id: int
    score: float | None  # None: fails a hard filter (see breakdown["fit_if_compatible"])
    breakdown: dict = field(default_factory=dict)


def hard_filters(mentee: dict, mentor: dict) -> tuple[dict[str, list], list[str]]:
    """Shared values per hard filter, and the filters the pair shares nothing on."""
    overlap, failed = {}, []
    for dim in HARD_FILTERS:
        a, b = set(mentee.get(dim) or []), set(mentor.get(dim) or [])
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


def _rescaled(a: list[float], b: list[float], band: tuple[float, float]) -> float:
    lo, hi = band
    return min(1.0, max(0.0, (_cosine(a, b) - lo) / (hi - lo)))


def text_similarity(mentee: dict, mentor: dict) -> dict[str, float]:
    """0-1 similarity per text box both sides have a vector for."""
    a, b = mentee.get("text_vectors") or {}, mentor.get("text_vectors") or {}
    return {f: _rescaled(a[f], b[f], SEMANTIC_RANGE) for f in embeddings.TEXT_FIELDS if f in a and f in b}


def shared_sectors(mentee: dict, mentor: dict) -> list[str]:
    def sectors(tags: dict) -> set[str]:
        return SECTORS.get((tags.get("industry") or "").strip().lower(), set())
    return sorted(sectors(mentee) & sectors(mentor))


def industry_similarity(mentee: dict, mentor: dict) -> float:
    """1 for the same industry; for a different one, the better of the shared-sector credit and
    the embedding similarity (see INDUSTRY_RANGE); 0 if unrelated."""
    if _same(mentee, mentor, "industry"):
        return 1.0
    a = (mentee.get("text_vectors") or {}).get("industry")
    b = (mentor.get("text_vectors") or {}).get("industry")
    embedded = _rescaled(a, b, INDUSTRY_RANGE) if a and b else 0.0
    return max(GROUP_CREDIT if shared_sectors(mentee, mentor) else 0.0, embedded)


def score_pair(mentee: dict, mentor: dict, weights: dict = WEIGHTS) -> tuple[float, dict]:
    total, used, breakdown = 0.0, 0.0, {}
    for dim, w in weights.items():
        if dim == "text":
            sims = text_similarity(mentee, mentor)
            if not sims:
                continue  # nothing to compare: leave text out of this pair's score
            sim = sum(sims.values()) / len(sims)
            shared = [f"{f.replace('_', ' ')} {round(100 * s)}%" for f, s in sims.items()]
        elif dim == "languages":
            shared = sorted((set(mentee.get(dim) or []) & set(mentor.get(dim) or [])) - {BASE_LANGUAGE})
            if not shared:
                continue  # English only, or nothing in common: no bonus, and no penalty either
            sim = 1.0
        elif dim == "industry":
            wanted = (mentee.get("industry") or "").strip()
            sim = industry_similarity(mentee, mentor) if wanted else 0.0
            if not wanted or not sim:
                shared = []
            elif _same(mentee, mentor, "industry"):
                shared = [mentor["industry"]]
            else:
                sector = ", ".join(shared_sectors(mentee, mentor))
                shared = [f"related{f' ({sector})' if sector else ''}: {mentor['industry']} {round(100 * sim)}%"]
        elif dim == "alumni":
            wanted = mentee.get("prefers_alumni")
            shared = [mentor["school"]] if wanted and _same(mentee, mentor, "school") else []
            sim = (1.0 if shared else 0.0) if wanted else 1.0
        else:
            picked = set(mentee.get(dim) or [])
            neutral = NEUTRAL.get(dim) in picked
            wanted = picked - {NEUTRAL.get(dim)}
            shared = sorted(wanted & set(mentor.get(dim) or []))
            if not wanted:
                sim = 0.0  # blank, or only the neutral tag (credited below)
            elif dim in PREFERENCE:
                sim = 1.0 if shared else 0.0
            else:
                sim = len(shared) / len(wanted)
            if neutral and sim < NEUTRAL_CREDIT:
                sim, shared = NEUTRAL_CREDIT, [NEUTRAL[dim]]
        total += w * sim
        used += w
        breakdown[dim] = {"coverage": round(sim, 3), "shared": shared, "weight": w}
    return round(100 * total / used, 1), breakdown


def rank_mentors(mentee: dict, mentors: dict[int, dict], open_slots: dict[int, int],
                 limit: int | None = None, excluded: set[int] = frozenset()) -> list[Candidate]:
    """Compatible mentors (sharing a time slot), best first.
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
    when nothing else is left, with breakdown["filters_failed"] naming what they don't share,
    score None, and the would-be score in breakdown["fit_if_compatible"].
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
                breakdown["fit_if_compatible"] = score
            pairs[i, j] = Candidate(mt, None if failed else score, breakdown)
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
            .filter(User.role == role, User.is_active, Application.status == "accepted")
            .all())
    return {p.user_id: _tags(p) for p in rows}


def open_slots() -> dict[int, int]:
    """1 for each accepted mentor with no approved or pending match, else 0 (one-to-one)."""
    taken = {m for (m,) in db.session.query(Match.mentor_id)
             .filter(Match.status.in_(("approved", "released", "proposed")))}
    return {mid: int(mid not in taken) for mid in accepted_profiles("mentor")}


def unmatched_mentee_ids() -> set[int]:
    matched = {m for (m,) in db.session.query(Match.mentee_id)
               .filter(Match.status.in_(("approved", "released", "proposed")))}
    awaiting_override = {mentee_id for (mentee_id,) in db.session.query(MatchOverrideRequest.mentee_id)
                         .filter_by(status="pending")}
    return set(accepted_profiles("mentee")) - matched - awaiting_override


def excluded_pairs() -> set[tuple[int, int]]:
    """(mentee_id, mentor_id) pairs staff rejected, or whose match was ended or withdrawn."""
    rejected = db.session.query(MatchExclusion.mentee_id, MatchExclusion.mentor_id)
    finished = db.session.query(Match.mentee_id, Match.mentor_id).filter(Match.status.in_(("ended", "withdrawn")))
    return {(me, mt) for me, mt in rejected.union(finished)}


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

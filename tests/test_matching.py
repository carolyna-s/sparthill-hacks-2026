from app import matching
from app.matching import SEMANTIC_RANGE, assign, rank_mentors, score_pair, text_similarity

MENTEE = {"industry": "Software Development", "goals": ["apply to grad school"],
          "development_areas": ["writing", "technical skills"]}


def test_full_coverage_scores_100():
    score, breakdown = score_pair(MENTEE, MENTEE)
    assert score == 100.0
    assert breakdown["goals"]["shared"] == ["apply to grad school"]


def test_partial_coverage_is_weighted():
    weights = {"industry": 0.4, "goals": 0.3, "development_areas": 0.3}
    mentor = {"industry": "Banking", "goals": [], "development_areas": ["writing"]}
    score, _ = score_pair(MENTEE, mentor, weights)
    assert score == 100 * (0.4 * 0 + 0.3 * 0 + 0.3 * 0.5)


def test_empty_mentee_dimension_does_not_penalize():
    score, _ = score_pair({"industry": "Law Practice"}, {"industry": "Law Practice"})
    assert score == 100.0


def test_industry_matches_ignoring_case_including_typed_values():
    weights = {"industry": 1.0}
    assert score_pair({"industry": "marine robotics"}, {"industry": "Marine Robotics "}, weights)[0] == 100.0
    assert score_pair({"industry": "Marine Robotics"}, {"industry": "Banking"}, weights)[0] == 0.0


def test_preference_dimensions_need_any_one_match():
    weights = {"education_paths": 1.0}
    mentee = {"education_paths": ["community college transfer", "first-generation college student"]}
    assert score_pair(mentee, {"education_paths": ["first-generation college student"]}, weights)[0] == 100.0
    assert score_pair(mentee, {"education_paths": ["graduate degree"]}, weights)[0] == 0.0


def test_alumni_only_counts_when_requested():
    weights = {"alumni": 1.0}
    mentor = {"school": "State University"}
    assert score_pair({"school": "Other U", "prefers_alumni": False}, mentor, weights)[0] == 100.0
    assert score_pair({"school": "Other U", "prefers_alumni": True}, mentor, weights)[0] == 0.0
    assert score_pair({"school": " state university", "prefers_alumni": True}, mentor, weights)[0] == 100.0


def test_hard_filters_drop_pairs_without_shared_time_or_language():
    mentee = {**MENTEE, "availability": ["Monday - morning"], "languages": ["English"]}
    mentors = {
        1: {**MENTEE, "availability": ["Monday - morning"], "languages": ["English", "Spanish"]},
        2: {**MENTEE, "availability": ["Tuesday - morning"], "languages": ["English"]},
        3: {**MENTEE, "availability": ["Monday - morning"], "languages": ["Spanish"]},
        4: MENTEE,  # no availability: not filtered; no languages: English
    }
    ranked = rank_mentors(mentee, mentors, open_slots={1: 1, 2: 1, 3: 1, 4: 1})
    assert [c.mentor_id for c in ranked] == [1, 4]
    assert ranked[0].breakdown["filters"] == {"availability": ["Monday - morning"], "languages": ["English"]}
    assert ranked[1].breakdown["filters"]["languages"] == ["English"]


def test_blank_language_means_english():
    mentors = {1: {"languages": ["Spanish"]}, 2: {"languages": ["Spanish", "English"]}, 3: {}}
    ranked = rank_mentors({}, mentors, open_slots={1: 1, 2: 1, 3: 1})
    assert [c.mentor_id for c in ranked] == [2, 3]


def test_rank_skips_full_mentors_and_orders_by_score():
    mentors = {1: MENTEE, 2: {"development_areas": ["writing"]}, 3: MENTEE}
    ranked = rank_mentors(MENTEE, mentors, open_slots={1: 1, 2: 1, 3: 0})
    assert [c.mentor_id for c in ranked] == [1, 2]


def test_assign_is_one_to_one():
    mentees = {10: MENTEE, 11: MENTEE, 12: MENTEE}
    mentors = {1: MENTEE, 2: {"development_areas": ["writing"]}}
    result = assign(mentees, mentors)
    assert len(result) == 2  # more mentees than mentors: one waits for the next run
    assert sorted(c.mentor_id for c in result.values()) == [1, 2]


def test_propose_all_on_seed_data(app):
    created = matching.propose_all()
    # Five accepted mentees compete for four mentor slots, so one remains unmatched.
    assert len(created) == 4
    assert len({m.mentee_id for m in created}) == len({m.mentor_id for m in created}) == 4
    assert len(matching.accepted_profiles("mentee")) == 5
    assert len(matching.unmatched_mentee_ids()) == 1
    assert matching.propose_all() == []


def test_text_similarity_is_rescaled_and_averaged_over_shared_answers():
    same, opposite = [1.0, 0.0], [0.0, 1.0]
    mentee = {"text_vectors": {"looking_for": same, "interests": same}}
    mentor = {"text_vectors": {"looking_for": same, "interests": opposite, "goals_other": same}}
    assert text_similarity(mentee, mentor) == {"interests": 0.0, "looking_for": 1.0}
    score, breakdown = score_pair(mentee, mentor, {"text": 1.0})
    assert score == 50.0
    assert breakdown["text"]["shared"] == ["interests 0%", "looking for 100%"]
    lo, hi = SEMANTIC_RANGE
    mid = (lo + hi) / 2
    assert abs(text_similarity({"text_vectors": {"interests": [mid, (1 - mid ** 2) ** 0.5]}},
                               {"text_vectors": {"interests": same}})["interests"] - 0.5) < 1e-9


def test_text_is_left_out_when_there_is_nothing_to_compare():
    weights = {"industry": 0.5, "text": 0.5}
    mentee = {"industry": "Banking", "text_vectors": {"looking_for": [1.0, 0.0]}}
    mentor = {"industry": "Banking", "text_vectors": {}}  # not embedded (no key, or blank)
    score, breakdown = score_pair(mentee, mentor, weights)
    assert score == 100.0 and "text" not in breakdown


def _fixed_scores(monkeypatch, table):
    """Make score_pair return table[(mentee_name, mentor_name)], keyed via a "name" tag."""
    monkeypatch.setattr(matching, "score_pair", lambda me, mt, weights=None: (table[me["name"], mt["name"]], {}))


def test_assign_maximizes_the_total_not_the_best_pair_first(monkeypatch):
    # Greedy takes A-X (90) first and leaves B with Y (10): total 100.
    # The Hungarian assignment gives A-Y (80) + B-X (85): total 165.
    _fixed_scores(monkeypatch, {("A", "X"): 90, ("A", "Y"): 80, ("B", "X"): 85, ("B", "Y"): 10})
    result = assign({1: {"name": "A"}, 2: {"name": "B"}}, {10: {"name": "X"}, 20: {"name": "Y"}})
    assert {me: c.mentor_id for me, c in result.items()} == {1: 20, 2: 10}


def test_assign_prefers_pairs_that_pass_the_hard_filters(monkeypatch):
    # B can only meet X (no shared time with Y), so A goes to Y even though A-X + B-Y scores higher.
    _fixed_scores(monkeypatch, {("A", "X"): 99, ("A", "Y"): 40, ("B", "X"): 30, ("B", "Y"): 95})
    mentees = {1: {"name": "A", "availability": ["Monday - morning", "Friday - morning"]},
               2: {"name": "B", "availability": ["Monday - morning"]}}
    mentors = {10: {"name": "X", "availability": ["Monday - morning"]},
               20: {"name": "Y", "availability": ["Friday - morning"]}}
    result = assign(mentees, mentors)
    assert {me: c.mentor_id for me, c in result.items()} == {1: 20, 2: 10}
    assert "filters_failed" not in result[1].breakdown


def test_assign_still_matches_the_last_pair_when_no_compatible_mentor_is_left(monkeypatch):
    _fixed_scores(monkeypatch, {("A", "X"): 10})
    result = assign({1: {"name": "A", "availability": ["Monday - morning"], "languages": ["Spanish"]}},
                    {10: {"name": "X", "availability": ["Friday - morning"], "languages": ["English"]}})
    assert result[1].mentor_id == 10
    assert result[1].breakdown["filters_failed"] == ["availability", "languages"]


def test_assign_never_uses_a_rejected_pair(monkeypatch):
    _fixed_scores(monkeypatch, {(a, b): 50 for a in "AB" for b in "XY"})
    mentees, mentors = {1: {"name": "A"}, 2: {"name": "B"}}, {10: {"name": "X"}, 20: {"name": "Y"}}
    result = assign(mentees, mentors, excluded={(1, 10)})
    assert {me: c.mentor_id for me, c in result.items()} == {1: 20, 2: 10}
    assert assign(mentees, {10: {"name": "X"}}, excluded={(1, 10)}).keys() == {2}

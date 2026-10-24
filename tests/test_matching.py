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


def test_assign_respects_capacity():
    mentees = {10: MENTEE, 11: MENTEE}
    mentors = {1: MENTEE, 2: {"development_areas": ["writing"]}}
    result = assign(mentees, mentors, open_slots={1: 1, 2: 1})
    assert sorted(c.mentor_id for c in result.values()) == [1, 2]


def test_propose_all_on_seed_data(app):
    created = matching.propose_all()
    # 4 accepted mentees, 4 accepted mentors, one-to-one: everyone gets a proposal, no one twice
    assert len(created) == 4
    assert len({m.mentee_id for m in created}) == 4
    assert len({m.mentor_id for m in created}) == 4
    assert all(n == 0 for n in matching.open_slots().values())
    assert matching.unmatched_mentee_ids() == set()
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

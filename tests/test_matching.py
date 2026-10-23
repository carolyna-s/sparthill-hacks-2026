from app import matching
from app.matching import assign, rank_mentors, score_pair

MENTEE = {"career_interests": ["data science", "healthcare"], "goals": ["apply to grad school"],
          "development_areas": ["writing", "technical skills"]}


def test_full_coverage_scores_100():
    score, breakdown = score_pair(MENTEE, MENTEE)
    assert score == 100.0
    assert breakdown["goals"]["shared"] == ["apply to grad school"]


def test_partial_coverage_is_weighted():
    weights = {"career_interests": 0.4, "goals": 0.3, "development_areas": 0.3}
    mentor = {"career_interests": ["data science"], "goals": [], "development_areas": ["writing", "technical skills"]}
    score, _ = score_pair(MENTEE, mentor, weights)
    assert score == 100 * (0.4 * 0.5 + 0.3 * 0 + 0.3 * 1)


def test_empty_mentee_dimension_does_not_penalize():
    score, _ = score_pair({"career_interests": ["law"]}, {"career_interests": ["law"]})
    assert score == 100.0


def test_preference_dimensions_need_any_one_match():
    weights = {"seniority": 1.0}
    mentee = {"seniority": ["mid-level (3-7 years)", "senior (7-15 years)"]}
    assert score_pair(mentee, {"seniority": ["senior (7-15 years)"]}, weights)[0] == 100.0
    assert score_pair(mentee, {"seniority": ["executive (15+ years)"]}, weights)[0] == 0.0


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
    mentors = {1: MENTEE, 2: {"career_interests": ["data science"]}, 3: MENTEE}
    ranked = rank_mentors(MENTEE, mentors, open_slots={1: 1, 2: 1, 3: 0})
    assert [c.mentor_id for c in ranked] == [1, 2]


def test_assign_respects_capacity():
    mentees = {10: MENTEE, 11: MENTEE}
    mentors = {1: MENTEE, 2: {"career_interests": ["data science"]}}
    result = assign(mentees, mentors, open_slots={1: 1, 2: 1})
    assert sorted(c.mentor_id for c in result.values()) == [1, 2]


def test_propose_all_on_seed_data(app):
    created = matching.propose_all()
    # 4 accepted mentees, 6 mentor slots: everyone gets a proposal, no one twice
    assert len(created) == 4
    assert len({m.mentee_id for m in created}) == 4
    assert matching.unmatched_mentee_ids() == set()
    assert matching.propose_all() == []

from app import matching
from app.matching import assign, rank_mentors, score_pair

MENTEE = {"career_interests": ["data science", "healthcare"], "goals": ["apply to grad school"],
          "development_areas": ["writing", "technical skills"]}


def test_full_coverage_scores_100():
    score, breakdown = score_pair(MENTEE, MENTEE)
    assert score == 100.0
    assert breakdown["goals"]["shared"] == ["apply to grad school"]


def test_partial_coverage_is_weighted():
    mentor = {"career_interests": ["data science"], "goals": [], "development_areas": ["writing", "technical skills"]}
    score, _ = score_pair(MENTEE, mentor)
    assert score == 100 * (0.4 * 0.5 + 0.3 * 0 + 0.3 * 1)


def test_empty_mentee_dimension_does_not_penalize():
    score, _ = score_pair({"career_interests": ["law"]}, {"career_interests": ["law"]})
    assert score == 100.0


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

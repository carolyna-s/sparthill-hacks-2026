"""HTTP flows for each role, checking what ends up in the database."""

import io
from datetime import timedelta

from app import matching
from app.extensions import db
from app.models import (Application, Attendance, AuditLog, Event, Feedback, Match, MatchExclusion, MatchFeedback,
                        MatchOverrideRequest, Meeting, Message, ReminderLog, Submission, User, utcnow)
from app.reminders import send_due_reminders

from .conftest import login


def test_healthz(client):
    assert client.get("/healthz").json == {"ok": True}


def test_account_profile_requires_password_and_keeps_identity_read_only(client):
    login(client, "jordan.kim@example.org")
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    page = client.get("/account")
    assert page.status_code == 200
    assert b'name="organization"' in page.data
    assert b'name="headline"' in page.data
    assert b'id="password-confirmation"' in page.data
    assert b'id="save-profile"' in page.data
    assert b'value="Jordan Kim" readonly' in page.data
    assert b'value="jordan.kim@example.org" readonly' in page.data

    response = client.post("/account", data={
        "action": "profile", "organization": "New Company", "headline": "New Role", "bio": "Updated bio",
        "linkedin_url": "https://www.linkedin.com/in/jordan", "current_password": "wrong",
        "name": "Changed Name", "email": "changed@example.org", "school": "Changed School",
    }, follow_redirects=True)
    assert b"That password is incorrect" in response.data
    assert b"passwordDialog.showModal()" in response.data
    assert user.profile.organization != "New Company"
    assert user.name == "Jordan Kim"
    assert user.email == "jordan.kim@example.org"

    response = client.post("/account", data={
        "action": "profile", "organization": "New Company", "headline": "New Role", "bio": "Updated bio",
        "linkedin_url": "https://[", "current_password": "password123",
    }, follow_redirects=True)
    assert b"Enter a valid LinkedIn URL" in response.data
    assert user.profile.organization != "New Company"

    response = client.post("/account", data={
        "action": "profile", "organization": "New Company", "headline": "New Role", "bio": "Updated bio",
        "linkedin_url": "https://www.linkedin.com/in/jordan", "current_password": "password123",
        "name": "Changed Name", "email": "changed@example.org", "school": "Changed School",
    }, follow_redirects=True)
    assert b"Profile changes saved." in response.data
    assert (user.profile.organization, user.profile.headline, user.profile.bio) == (
        "New Company", "New Role", "Updated bio")
    assert user.profile.linkedin_url == "https://www.linkedin.com/in/jordan"
    assert user.name == "Jordan Kim"
    assert user.email == "jordan.kim@example.org"
    assert user.profile.school != "Changed School"


def test_account_password_change_validates_and_updates(client):
    login(client, "jordan.kim@example.org")
    response = client.post("/account", data={
        "action": "password", "current_password": "wrong", "new_password": "newpassword",
        "confirm_password": "newpassword",
    }, follow_redirects=True)
    assert b"Your current password is incorrect." in response.data
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    assert user.check_password("password123")

    response = client.post("/account", data={
        "action": "password", "current_password": "password123", "new_password": "newpassword",
        "confirm_password": "different",
    }, follow_redirects=True)
    assert b"New password and confirmation do not match." in response.data
    response = client.post("/account", data={
        "action": "password", "current_password": "password123", "new_password": "short",
        "confirm_password": "short",
    }, follow_redirects=True)
    assert b"New password must be at least 8 characters." in response.data
    response = client.post("/account", data={
        "action": "password", "current_password": "password123", "new_password": "newpassword",
        "confirm_password": "newpassword",
    }, follow_redirects=True)
    assert b"Password changed successfully." in response.data
    assert user.check_password("newpassword")


def test_dashboard_application_edits_answers_without_changing_status(client):
    login(client, "jordan.kim@example.org")
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    app_row = user.application
    original_status = app_row.status
    original_submitted_at = app_row.submitted_at
    page = client.get("/dashboard")
    assert b"Submitted Mentee Application" in page.data
    assert b'href="/dashboard/application"' in page.data
    assert b'name="mentorship_style"' not in page.data
    page = client.get("/dashboard/application")
    assert b"Submitted Mentee Application" in page.data
    assert b'value="Jordan Kim" readonly' in page.data
    assert b'name="organization"' in page.data
    assert b'name="availability"' in page.data
    assert b'name="languages"' in page.data
    assert b'name="industry"' in page.data
    assert b'name="development_areas"' in page.data
    assert b'name="goals"' in page.data
    assert b'name="education_paths"' in page.data
    assert b'name="interests"' in page.data
    assert b'name="mentorship_style"' in page.data
    assert b'name="career_advice"' in page.data
    assert b'name="organization" value="" maxlength="200" data-editable disabled' in page.data
    assert b"grid-cols-[auto_repeat(4,minmax(0,1fr))]" in page.data
    assert b"6am\xe2\x80\x9312pm" in page.data
    assert b"Monday" in page.data and b"Night" in page.data

    response = client.post("/dashboard/application", data={
        "organization": "Updated Org", "headline": "Updated role", "bio": "Updated bio",
        "linkedin_url": "https://example.org/profile", "availability": ["Monday - night"],
        "languages": ["Spanish"], "industry": "Software Development",
        "development_areas": ["leadership"], "goals": ["land first job"],
        "goals_other": "Start a community", "education_paths": ["graduate degree"],
        "interests": "Updated interests", "prefers_alumni": "1",
        "mentorship_style": "Updated style", "career_advice": "Updated advice",
        "name": "Changed Name", "email": "changed@example.org", "school": "Changed School",
    }, follow_redirects=True)
    assert b"Application changes saved." in response.data
    assert response.request.path == "/dashboard/application"
    assert app_row.answers == {
        "mentorship_style": "Updated style", "career_advice": "Updated advice",
    }
    assert user.profile.organization == "Updated Org"
    assert user.profile.availability == ["Monday - night"]
    assert user.profile.languages == ["English", "Spanish"]  # English is always included
    assert user.profile.industry == "Software Development"
    assert user.profile.interests == "Updated interests"
    assert user.profile.prefers_alumni
    assert app_row.status == original_status
    assert app_row.submitted_at == original_submitted_at
    assert user.name == "Jordan Kim"
    assert user.email == "jordan.kim@example.org"


def test_mentee_intake_flow(client):
    client.post("/register", data={"role": "mentee", "name": "New Person", "email": "new@x.org",
                                   "password": "longenough", "school": "State University"})
    user = db.session.query(User).filter_by(email="new@x.org").one()
    blocked = client.get("/dashboard", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/2")
    assert b"Please complete onboarding to access Dashboard" in blocked.data
    assert client.get("/profile").headers["Location"].endswith("/profile/2")  # step 1 done at sign-up
    blocked = client.get("/profile/3", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/2")  # locked until step 2 is done

    resp = client.post("/profile/1", data={"name": "New Person", "email": "new@x.org", "school": "State University",
                                           "bio": "Hi", "linkedin_url": "https://www.linkedin.com/in/np"})
    assert resp.headers["Location"].endswith("/profile/2")
    assert user.profile.linkedin_url == "https://www.linkedin.com/in/np"

    resp = client.post("/profile/2", data={"availability": ["Monday - night", "Funday - noon"], "languages": ["Spanish"]})
    assert resp.headers["Location"].endswith("/profile/3")
    assert user.profile.availability == ["Monday - night"]

    blocked = client.get("/modules", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/3")
    assert b"Please complete onboarding to access Modules" in blocked.data

    resp = client.post("/profile/3", data={"goals": ["switch careers", "not-a-real-tag"], "goals_other": "write a book",
                                           "industry": "  software   DEVELOPMENT ", "prefers_alumni": "1"})
    assert resp.headers["Location"].endswith("/profile/4")
    assert user.profile.goals == ["switch careers"]
    assert user.profile.goals_other == "write a book"
    assert user.profile.industry == "Software Development"  # snapped to the suggestion's spelling
    assert user.profile.prefers_alumni

    blocked = client.get("/messages/", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding to access Messages" in blocked.data
    blocked = client.get("/profile", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding" not in blocked.data

    resp = client.post("/profile/4", data={
        "interests": "Product design",
        "looking_for": "Interview practice",
        "mentorship_style": "Clear communication",
    })
    assert resp.headers["Location"].endswith("/profile/4")  # career advice is required
    blocked = client.get("/dashboard", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding to access Dashboard" in blocked.data
    client.post("/logout")
    login_response = client.post("/login", data={"email": "new@x.org", "password": "longenough"})
    assert login_response.headers["Location"].endswith("/profile")
    onboarding = client.get(login_response.headers["Location"], follow_redirects=True)
    assert onboarding.request.path.endswith("/profile/4")
    assert b"Please complete onboarding" not in onboarding.data
    blocked = client.get("/dashboard", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding to access Dashboard" in blocked.data

    back = client.post("/profile/4", data={
        "nav": "back",
        "interests": "Product design",
        "looking_for": "Interview practice",
        "mentorship_style": "Clear communication",
    }, follow_redirects=True)
    assert back.request.path.endswith("/profile/3")
    blocked = client.get("/dashboard", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/3")
    assert b"Please complete onboarding to access Dashboard" in blocked.data
    assert client.post("/profile/3", data={}).headers["Location"].endswith("/profile/4")

    profile_page = client.get("/profile/4")
    assert b"What subjects are you interested in learning more about?" in profile_page.data
    assert b"What communication or mentorship style helps you learn most effectively?" in profile_page.data
    assert b"What type of advice would you like to receive as you begin or develop your career?" in profile_page.data

    resp = client.post("/profile/4", data={
        "interests": "Product design",
        "looking_for": "Interview practice",
        "mentorship_style": "Clear communication",
        "career_advice": "Actionable career guidance",
    })
    assert resp.headers["Location"].endswith("/apply")
    assert user.profile.looking_for == "Interview practice"
    assert user.application.answers == {
        "mentorship_style": "Clear communication",
        "career_advice": "Actionable career guidance",
    }
    assert client.get("/dashboard").headers["Location"].endswith("/agreements")

    client.post("/apply", data={"action": "submit"})
    assert user.application.status == "draft"  # agreement not signed yet
    assert client.get("/dashboard").headers["Location"].endswith("/agreements")  # locked until sign-up is done

    assert client.post("/agreements/1/sign", data={"typed_name": "New Person"}).headers["Location"].endswith("/apply")
    assert client.get("/dashboard").headers["Location"].endswith("/apply")
    assert client.post("/apply", data={"action": "submit"}).headers["Location"].endswith("/dashboard")
    db.session.refresh(user.application)
    assert user.application.status == "submitted"  # free-response answers are optional
    assert client.get("/dashboard").status_code == 200


def test_profile_back_saves_without_requiring(client):
    client.post("/register", data={"role": "mentee", "name": "Back Person", "email": "bp@x.org",
                                   "password": "longenough", "school": "State University"})
    resp = client.post("/profile/2", data={"nav": "back", "languages": ["Korean"]})
    assert resp.headers["Location"].endswith("/profile/1")
    user = db.session.query(User).filter_by(email="bp@x.org").one()
    assert user.profile.languages == ["English", "Korean"]


def test_register_requires_school(client):
    client.post("/register", data={"role": "mentee", "name": "No School", "email": "ns@x.org",
                                   "password": "longenough", "school": "  "})
    assert db.session.query(User).filter_by(email="ns@x.org").first() is None


def test_required_fields_block_next(client):
    client.post("/register", data={"role": "mentor", "name": "New Mentor", "email": "nm@x.org",
                                   "password": "longenough", "school": "City College"})
    resp = client.post("/profile/1", data={"name": "New Mentor", "email": "nm@x.org", "school": " "})
    assert resp.headers["Location"].endswith("/profile/1")  # school is required
    resp = client.post("/profile/1", data={"name": "New Mentor", "email": "jordan.kim@example.org", "school": "CC"})
    assert resp.headers["Location"].endswith("/profile/1")  # email taken
    user = db.session.query(User).filter_by(email="nm@x.org").one()
    assert user.profile.school == "CC"

    resp = client.post("/profile/2", data={"languages": ["Spanish"]})
    assert resp.headers["Location"].endswith("/profile/2")  # availability is required too
    resp = client.post("/profile/2", data={"availability": ["Friday - afternoon"]})
    assert resp.headers["Location"].endswith("/profile/3")  # no extra language needed: English is included
    assert user.profile.languages == ["English"]
    client.post("/profile/3", data={})
    profile_page = client.get("/profile/4")
    assert b"Relating to your industry experience, what do you bring to the table?" in profile_page.data
    assert b"What type of mentor do you see yourself being?" in profile_page.data
    assert b"What type of advice would you give someone beginning their career in your field?" in profile_page.data


def test_staff_pages_are_staff_only(client):
    login(client, "jordan.kim@example.org")
    assert client.get("/staff/").status_code == 403
    login(client, "staff.admin@example.org")
    for path in ["/staff/", "/staff/applications", "/staff/matching", "/staff/reports",
                 "/staff/modules/new"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/staff/people").status_code == 302
    overview = client.get("/staff/").data
    assert b"Dashboard" in overview
    assert b"Staff Overview" in overview


def test_review_match_and_message(client):
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").one()
    client.post(f"/staff/applications/{pending.id}", data={"decision": "accepted"})
    assert pending.status == "accepted"

    client.post("/staff/matching/propose-all")
    proposed = db.session.query(Match).filter_by(status="proposed").all()
    assert len(proposed) == 4  # 5 accepted mentees, 4 mentors, one mentee each
    assert len({m.mentor_id for m in proposed}) == 4
    for m in proposed:
        client.post(f"/staff/matches/{m.id}/approve")
    match = proposed[0]
    assert match.status == "released"

    login(client, match.mentee.email)
    inbox = client.get("/messages/")
    assert inbox.status_code == 200 and b"awaiting confirmation" in inbox.data
    dashboard = client.get("/dashboard")
    assert b"Action required:" in dashboard.data
    assert b"Confirm or decline this match" in dashboard.data
    notification = client.get(f"/matches/{match.id}/confirmation")
    assert notification.status_code == 200
    assert b"Confirm match" in notification.data and b"Decline match" in notification.data
    client.post(f"/matches/{match.id}/confirmation", data={"response": "confirm"})
    assert match.status == "approved" and match.mentee_confirmed_at is not None
    assert client.get("/messages/").headers["Location"].endswith(f"/messages/{match.id}")
    client.post(f"/messages/{match.id}", data={"body": "Hi!"})
    page = client.get(f"/messages/{match.id}")
    assert f"Messages with your mentor, {match.mentor.name}".encode() in page.data
    assert b"Sent" in page.data and b"Seen" not in page.data
    login(client, match.mentor.email)
    page = client.get(f"/messages/{match.id}")
    assert b"Hi!" in page.data
    assert f"Messages with your mentee, {match.mentee.name}".encode() in page.data
    assert b"Active now" in page.data  # the mentee was just here
    assert db.session.query(Message).one().read_at is not None
    login(client, match.mentee.email)
    assert b"Seen just now" in client.get(f"/messages/{match.id}").data

    outsider = next(m for m in proposed if not m.includes(match.mentor))
    assert client.get(f"/messages/{outsider.id}").status_code == 404


def test_mentor_schedules_meeting_on_both_calendars(client):
    from app import matching

    match = matching.propose_all()[0]
    match.status = "approved"
    db.session.commit()
    when = utcnow().replace(hour=15, minute=30, second=0, microsecond=0)

    login(client, match.mentee.email)
    assert client.post(f"/messages/{match.id}/meetings", data={"starts_at": when.isoformat()}).status_code == 403
    login(client, match.mentor.email)
    client.post(f"/messages/{match.id}/meetings", data={"starts_at": when.strftime("%Y-%m-%dT%H:%M"), "note": "Zoom"})
    meeting = db.session.query(Meeting).one()
    assert meeting.starts_at == when
    assert b"Scheduled a meeting" in client.get(f"/messages/{match.id}").data
    assert f"Meeting with {match.mentee.name}".encode() in client.get("/dashboard").data

    login(client, match.mentee.email)
    dashboard = client.get("/dashboard").data
    assert f"Meeting with {match.mentor.name}".encode() in dashboard
    assert b"To do" in dashboard
    login(client, match.mentor.email)
    assert b"To do" not in client.get("/dashboard").data  # modules' to-do is for mentees

    client.post(f"/meetings/{meeting.id}/cancel")
    assert db.session.query(Meeting).count() == 0


def test_reject_match_needs_reason_and_is_never_reproposed(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    m, m2 = db.session.query(Match).filter_by(status="proposed").limit(2).all()
    overview = client.get(f"/staff/matches/{m.id}").data
    assert b"Approve\xe2\x80\xa6" in overview and b"Reject\xe2\x80\xa6" in overview  # "More info": both options
    reject_page = client.get(f"/staff/matches/{m.id}?action=reject").data
    assert b"Reject match" in reject_page and b"Confirm approval" not in reject_page
    assert b"Cancel proposal" not in reject_page and b"Gut feeling" not in reject_page
    approve_page = client.get(f"/staff/matches/{m.id}?action=approve").data
    assert b"Confirm approval" in approve_page and b"Reject match" not in approve_page

    client.post(f"/staff/matches/{m.id}/reject")  # no reason
    client.post(f"/staff/matches/{m.id}/reject", data={"reason": "gut_feeling"})  # no longer an option
    client.post(f"/staff/matches/{m.id}/reject", data={"reason": "other", "comment": "  "})  # other needs text
    assert m.status == "proposed" and db.session.query(MatchFeedback).count() == 0

    client.post(f"/staff/matches/{m.id}/reject",
                data={"reason": "other", "comment": "Their goals don't line up."})
    assert m.status == "rejected"
    f = db.session.query(MatchFeedback).one()
    assert (f.kind, f.reason, f.comment) == ("deny", "other", "Their goals don't line up.")
    assert db.session.query(MatchExclusion).filter_by(mentee_id=m.mentee_id, mentor_id=m.mentor_id).count() == 1
    client.post(f"/staff/matches/{m2.id}/reject", data={"reason": "experience_gap"})  # listed reasons need no text
    assert m2.status == "rejected"

    client.post("/staff/matching/propose-all")
    assert db.session.query(Match).filter_by(mentee_id=m.mentee_id, mentor_id=m.mentor_id).count() == 1
    assert b"goals don&#39;t line up" in client.get("/staff/matching").data
    assert b"goals don&#39;t line up" in client.get(f"/staff/people/{m.mentee_id}").data


def test_match_review_queue_advances_until_all_proposals_are_done(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    ordered = (db.session.query(Match).filter_by(status="proposed")
               .order_by(Match.score.desc(), Match.id.asc()).all())
    first = ordered[0]
    review = client.get(f"/staff/matches/{first.id}?action=approve&queue=1")
    assert b"Exit review queue" in review.data
    assert b'name="queue" value="1"' in review.data

    response = client.post(f"/staff/matches/{first.id}/approve", data={"queue": "1"})
    remaining = ordered[1:]
    if remaining:
        assert response.location.endswith(f"/staff/matches/{remaining[0].id}?queue=1")
    else:
        assert response.location.endswith("/staff/matching")

    for match in remaining:
        response = client.post(
            f"/staff/matches/{match.id}/reject",
            data={"queue": "1", "reason": "experience_gap"},
        )
    assert response.location.endswith("/staff/matching")
    assert b"All proposed matches have been reviewed." in client.get(response.location).data
    assert db.session.query(Match).filter_by(status="proposed").count() == 0


def test_staff_manual_match_override_requires_capacity_and_logs_change(client):
    login(client, "staff.admin@example.org")
    mentee_id = min(matching.unmatched_mentee_ids())
    mentor_id = next(iter(matching.accepted_profiles("mentor")))

    start = client.post("/staff/matching/override/start", data={"mentee_id": mentee_id})
    assert start.location.endswith(f"/staff/matching?override_mentee={mentee_id}")
    page = client.get(start.location)
    assert b"Override matchmaker" in page.data
    assert b"Mentor currently has " in page.data

    response = client.post(
        "/staff/matching/override",
        data={"mentee_id": mentee_id, "mentor_id": mentor_id},
    )
    assert response.location.endswith("/staff/matching")
    manual_match = db.session.query(Match).filter_by(mentee_id=mentee_id, mentor_id=mentor_id).one()
    assert manual_match.status == "released"
    assert manual_match.score_breakdown == {"manual_override": True}
    assert db.session.query(AuditLog).filter_by(action="manual_match_override").count() == 1

    another_mentee_id = min(matching.unmatched_mentee_ids())
    ticket_response = client.post(
        "/staff/matching/override",
        data={"mentee_id": another_mentee_id, "mentor_id": mentor_id},
        follow_redirects=True,
    )
    assert b"sent to the backend admin" in ticket_response.data
    assert db.session.query(Match).filter_by(mentee_id=another_mentee_id, mentor_id=mentor_id).count() == 0
    ticket = db.session.query(MatchOverrideRequest).filter_by(mentee_id=another_mentee_id).one()
    assert ticket.status == "pending"
    assert another_mentee_id not in matching.unmatched_mentee_ids()

    login(client, "backend.admin@example.org")
    admin_page = client.get("/admin/")
    assert b"Capacity override requests" in admin_page.data
    assert b"Approve" in admin_page.data and b"Deny" in admin_page.data
    client.post(f"/admin/matching-override-requests/{ticket.id}/approve")
    assert ticket.status == "approved"
    over_capacity_match = db.session.get(Match, ticket.match_id)
    assert over_capacity_match.status == "released"
    assert over_capacity_match.score_breakdown["admin_approved_over_capacity"] is True
    assert over_capacity_match.mentee_confirmed_at is None
    assert db.session.query(AuditLog).filter_by(
        action="manual_match_override_approved", target_user_id=another_mentee_id
    ).count() == 1

    login(client, over_capacity_match.mentee.email)
    mentee_dashboard = client.get("/dashboard")
    assert b"Your match" in mentee_dashboard.data
    assert b"Action required:" in mentee_dashboard.data
    assert b"Open match notification" in mentee_dashboard.data
    client.post(f"/matches/{over_capacity_match.id}/confirmation", data={"response": "confirm"})
    assert over_capacity_match.status == "released"
    assert over_capacity_match.mentee_confirmed_at is not None
    assert b"Waiting for the mentor" in client.get("/dashboard").data

    login(client, over_capacity_match.mentor.email)
    mentor_dashboard = client.get("/dashboard")
    assert b"Your mentees" in mentor_dashboard.data
    assert b"confirm or deny this over-capacity match" in mentor_dashboard.data
    assert b"Open match notification" in mentor_dashboard.data
    assert client.get(f"/matches/{over_capacity_match.id}/confirmation").status_code == 200
    client.post(f"/matches/{over_capacity_match.id}/confirmation", data={"response": "confirm"})
    assert over_capacity_match.status == "approved"
    assert over_capacity_match.mentor_confirmed_at is not None

    denied_mentee_id = min(matching.unmatched_mentee_ids())
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/override", data={
        "mentee_id": denied_mentee_id, "mentor_id": mentor_id,
    })
    denied_ticket = db.session.query(MatchOverrideRequest).filter_by(
        mentee_id=denied_mentee_id, status="pending"
    ).one()
    login(client, "backend.admin@example.org")
    client.post(f"/admin/matching-override-requests/{denied_ticket.id}/deny")
    assert denied_ticket.status == "denied"
    assert denied_mentee_id in matching.unmatched_mentee_ids()


def test_capacity_override_mentor_can_deny_and_returns_mentee_to_pool(client):
    from app.seed import seed_pool

    login(client, "staff.admin@example.org")
    seed_pool()
    mentor_id = next(iter(matching.accepted_profiles("mentor")))
    accepted_mentees = sorted(matching.accepted_profiles("mentee"))
    existing_match = Match(
        mentee_id=accepted_mentees[0], mentor_id=mentor_id, status="approved", score=80,
    )
    db.session.add(existing_match)
    db.session.commit()
    mentee_id = min(matching.unmatched_mentee_ids())
    response = client.post("/staff/matching/override", data={
        "mentee_id": mentee_id, "mentor_id": mentor_id,
    })
    assert response.status_code == 302
    ticket = db.session.query(MatchOverrideRequest).filter_by(mentee_id=mentee_id).one()

    login(client, "backend.admin@example.org")
    client.post(f"/admin/matching-override-requests/{ticket.id}/approve")
    override_match = db.session.get(Match, ticket.match_id)
    assert override_match.status == "released"

    login(client, override_match.mentor.email)
    dashboard = client.get("/dashboard")
    assert b"confirm or deny this over-capacity match" in dashboard.data
    client.post(f"/matches/{override_match.id}/confirmation", data={"response": "decline"})

    assert override_match.status == "rejected"
    assert mentee_id in matching.unmatched_mentee_ids()
    feedback = db.session.query(MatchFeedback).filter_by(
        match_id=override_match.id, reason="mentor_rejection"
    ).one()
    assert feedback.kind == "deny"
    login(client, "staff.admin@example.org")
    assert b"Mentor Rejection" in client.get("/staff/matching").data


def test_mentee_declining_a_mentor_returns_to_pool_and_appears_in_staff_rejections(client):
    login(client, "staff.admin@example.org")
    match = matching.propose_all()[0]
    client.post(f"/staff/matches/{match.id}/approve")

    login(client, match.mentee.email)
    response = client.post(f"/matches/{match.id}/confirmation", data={
        "response": "decline", "reason": "mentee_rejection",
    })
    assert response.status_code == 302
    assert match.status == "rejected"
    assert match.mentee_id in matching.unmatched_mentee_ids()
    assert db.session.query(MatchExclusion).filter_by(
        mentee_id=match.mentee_id, mentor_id=match.mentor_id
    ).count() == 1
    feedback = db.session.query(MatchFeedback).filter_by(match_id=match.id, kind="deny").one()
    assert (feedback.kind, feedback.reason, feedback.wants_rematch) == (
        "deny", "mentee_rejection", True)

    login(client, "staff.admin@example.org")
    page = client.get("/staff/matching")
    assert b"Mentee Rejection" in page.data
    assert match.mentee.name.encode() in page.data


def test_mentee_withdrawal_leaves_program_and_is_not_rematched(client):
    login(client, "staff.admin@example.org")
    match = matching.propose_all()[0]
    client.post(f"/staff/matches/{match.id}/approve")
    login(client, match.mentee.email)

    response = client.post(f"/matches/{match.id}/confirmation", data={
        "response": "decline", "reason": "mentee_withdrawn",
    })
    assert response.status_code == 302
    assert match.status == "withdrawn"
    assert match.mentee.application.status == "withdrawn"
    assert match.mentee_id not in matching.unmatched_mentee_ids()
    feedback = db.session.query(MatchFeedback).filter_by(match_id=match.id).one()
    assert (feedback.kind, feedback.reason, feedback.wants_rematch) == (
        "withdraw", "mentee_withdrawn", False)

    login(client, "staff.admin@example.org")
    assert b"Mentee Withdrawn" in client.get("/staff/matching").data


def test_mentee_releasing_confirmed_mentor_returns_to_pool(client):
    login(client, "staff.admin@example.org")
    match = matching.propose_all()[0]
    client.post(f"/staff/matches/{match.id}/approve")
    login(client, match.mentee.email)
    client.post(f"/matches/{match.id}/confirmation", data={"response": "confirm"})
    response = client.post(f"/matches/{match.id}/release")

    assert response.status_code == 302
    assert match.status == "withdrawn"
    assert match.mentee_id in matching.unmatched_mentee_ids()
    assert all(candidate.mentor_id != match.mentor_id
               for candidate in matching.ranking_for(match.mentee_id, limit=None))
    feedback = db.session.query(MatchFeedback).filter_by(match_id=match.id, kind="deny").one()
    assert (feedback.reason, feedback.wants_rematch) == ("mentee_rejection", True)


def test_undo_auto_propose_and_cancel(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    proposed = db.session.query(Match).filter_by(status="proposed").all()
    banner = f"Proposed {len(proposed)} matches.".encode()
    assert banner in client.get("/staff/matching").data
    assert banner not in client.get("/staff/matching").data  # the undo offer shows once

    client.post("/staff/matching/cancel", data={"ids": [m.id for m in proposed[:2]]})
    assert db.session.query(Match).count() == len(proposed) - 2
    client.post("/staff/matching/cancel", data={"all": 1})
    assert db.session.query(Match).count() == 0


def test_undo_reject_and_end(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    a, b = db.session.query(Match).filter_by(status="proposed").limit(2).all()

    client.post(f"/staff/matches/{a.id}/approve")
    assert client.post(f"/staff/matches/{a.id}/unapprove").status_code == 400  # approval is final
    assert a.status == "released"
    login(client, a.mentee.email)
    client.post(f"/matches/{a.id}/confirmation", data={"response": "confirm"})
    login(client, "staff.admin@example.org")
    client.post(f"/staff/matches/{a.id}/end")
    client.post(f"/staff/matches/{a.id}/reopen")
    assert a.status == "approved"

    client.post(f"/staff/matches/{b.id}/reject", data={"reason": "fit_concern", "comment": "Mismatch."})
    client.post(f"/staff/matches/{b.id}/unreject")
    assert b.status == "proposed"
    assert db.session.query(MatchFeedback).filter_by(match_id=b.id).count() == 0
    assert db.session.query(MatchExclusion).count() == 0

    client.post(f"/staff/matches/{a.id}/reopen")  # already approved: refused, nothing breaks
    assert a.status == "approved"


def test_ended_pair_is_not_proposed_again(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    m = db.session.query(Match).filter_by(status="proposed").first()
    pair = (m.mentee_id, m.mentor_id)
    client.post(f"/staff/matches/{m.id}/approve")
    login(client, m.mentee.email)
    client.post(f"/matches/{m.id}/confirmation", data={"response": "confirm"})
    login(client, "staff.admin@example.org")
    client.post(f"/staff/matches/{m.id}/end")

    assert m.mentee_id in matching.unmatched_mentee_ids()  # both are back in the pool...
    assert all(c.mentor_id != m.mentor_id for c in matching.ranking_for(m.mentee_id, limit=None))
    client.post("/staff/matching/propose-all")
    proposed = {(x.mentee_id, x.mentor_id) for x in db.session.query(Match).filter_by(status="proposed")}
    assert pair not in proposed  # ...but not with each other


def test_undo_application_decision(client):
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").one()
    client.post(f"/staff/applications/{pending.id}", data={"decision": "rejected"})
    assert pending.status == "rejected"
    assert b"Undo" in client.get("/staff/applications").data
    client.post(f"/staff/applications/{pending.id}/undo", data={"status": "submitted"})
    assert pending.status == "submitted"



def test_rematch_keeps_approved_and_reruns_only_rejected_and_unmatched(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    ids = {u.email.split("@")[0]: u.id for u in db.session.query(User)}
    proposed = db.session.query(Match).filter_by(status="proposed").all()
    assert {(m.mentee_id, m.mentor_id) for m in proposed} >= {(ids["jordan.kim"], ids["priya.raman"]),
                                                              (ids["riley.chen"], ids["sam.okafor"])}
    deny = [m for m in proposed if m.mentee_id in (ids["jordan.kim"], ids["riley.chen"])]
    keep = [m for m in proposed if m not in deny]
    for m in keep:
        client.post(f"/staff/matches/{m.id}/approve")
    for m in deny:
        client.post(f"/staff/matches/{m.id}/reject", data={"reason": "fit_concern", "comment": "Not a fit."})
    approved = {(m.mentee_id, m.mentor_id) for m in keep}

    # Pool: Jordan and Riley, with Priya and Sam free. Neither pair shares a time slot, and the
    # rejected pairs are out, so they're matched anyway and flagged.
    client.post("/staff/matching/propose-all")
    assert {(m.mentee_id, m.mentor_id) for m in db.session.query(Match).filter_by(status="released")} == approved
    redo = {m.mentee_id: m for m in db.session.query(Match).filter_by(status="proposed")}
    assert {me: m.mentor_id for me, m in redo.items()} == {ids["jordan.kim"]: ids["sam.okafor"],
                                                          ids["riley.chen"]: ids["priya.raman"]}
    assert all(m.rematch_round == 2 and m.score_breakdown["filters_failed"] == ["availability"]
               for m in redo.values())
    page = client.get("/staff/matching").data
    assert b"re-match #2" in page and b"No shared availability" in page

def test_staff_people_dashboards(client):
    login(client, "staff.admin@example.org")
    response = client.get("/staff/people?role=mentee&q=jordan")
    assert response.status_code == 302
    page = client.get(response.headers["Location"]).data
    assert b"Jordan Kim" in page
    jordan = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    assert client.get(f"/staff/people/{jordan.id}").status_code == 200
    staff = db.session.query(User).filter_by(role="staff").first()
    assert client.get(f"/staff/people/{staff.id}").status_code == 404
    login(client, "jordan.kim@example.org")
    assert client.get("/staff/people").status_code == 403


def test_event_submission_checkin_feedback(client):
    event = db.session.query(Event).first()
    login(client, "jordan.kim@example.org")
    client.post(f"/modules/{event.id}/submit/prework",
                data={"body": "my goals", "file": (io.BytesIO(b"pdf"), "goals.pdf")},
                content_type="multipart/form-data")
    sub = db.session.query(Submission).one()
    assert sub.file_name == "goals.pdf"
    assert client.get(f"/submissions/{sub.id}/file").data == b"pdf"

    client.post(f"/modules/{event.id}/checkin", data={"code": "wrong"})
    assert db.session.query(Attendance).count() == 0
    client.post(f"/modules/{event.id}/checkin", data={"code": event.checkin_code.lower()})
    assert db.session.query(Attendance).count() == 1

    client.post("/feedback", data={"event_id": event.id, "rating": 4})
    login(client, "staff.admin@example.org")
    assert b"4.0" in client.get("/staff/reports").data


def test_staff_report_module_shows_attended_and_absent_users(client):
    event = db.session.query(Event).first()
    event.starts_at = utcnow() + timedelta(hours=1)
    event.location = "Main Hall"
    event.description = "Workshop description"
    event.prework_prompt = "Bring a draft resume."
    event.prework_due = utcnow() + timedelta(minutes=30)
    event.postwork_prompt = "Write a reflection."
    event.postwork_due = utcnow() + timedelta(days=1)
    jordan = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    db.session.add_all([
        Attendance(event_id=event.id, user_id=jordan.id),
        Submission(event_id=event.id, user_id=jordan.id, kind="prework", body="Ready."),
        Feedback(user_id=jordan.id, event_id=event.id, rating=4),
    ])
    db.session.commit()

    login(client, "staff.admin@example.org")
    reports = client.get("/staff/reports")
    assert reports.status_code == 200
    assert f"/staff/reports/modules/{event.id}".encode() in reports.data
    response = client.get(f"/staff/reports/modules/{event.id}")
    assert response.status_code == 200
    assert b"Attended (1)" in response.data
    assert jordan.name.encode() in response.data
    assert b"Did not attend (" in response.data
    assert b"Priya Raman" in response.data
    for detail in (b"Module details", b"Main Hall", b"Workshop description", b"Bring a draft resume.",
                   b"Write a reflection.", b"Prework submitted", b"Postwork submitted", b"Average rating",
                   b"4.0", b"submitted"):
        assert detail in response.data


def test_postwork_opens_after_session(client):
    event = db.session.query(Event).first()
    login(client, "jordan.kim@example.org")
    assert b"Opens after the session" in client.get(f"/modules/{event.id}").data
    client.post(f"/modules/{event.id}/submit/postwork", data={"body": "too early"})
    assert db.session.query(Submission).count() == 0

    event.starts_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    client.post(f"/modules/{event.id}/submit/postwork", data={"body": "done"})
    assert db.session.query(Submission).one().kind == "postwork"


def test_mentor_sees_assignments_and_mentee_submissions(client):
    from app import matching

    match = matching.propose_all()[0]
    match.status = "approved"
    db.session.commit()
    event = db.session.query(Event).first()

    login(client, match.mentee.email)
    client.post(f"/modules/{event.id}/submit/prework",
                data={"body": "my resume", "file": (io.BytesIO(b"pdf"), "resume.pdf")},
                content_type="multipart/form-data")
    sub = db.session.query(Submission).one()

    login(client, match.mentor.email)
    page = client.get(f"/modules/{event.id}").data
    assert b"my resume" in page and b"resume.pdf" in page
    assert b'name="body"' not in page  # read-only: no submission form
    assert b"1/1 mentees submitted" in client.get("/modules").data
    assert client.get(f"/submissions/{sub.id}/file").data == b"pdf"
    assert client.post(f"/modules/{event.id}/submit/prework", data={"body": "x"}).status_code == 403

    other_mentor = next(u for u in db.session.query(User).filter_by(role="mentor") if u.id != match.mentor_id)
    login(client, other_mentor.email)
    assert client.get(f"/submissions/{sub.id}/file").status_code == 404


def test_reminders_are_sent_once(client):
    first = send_due_reminders()
    assert first > 0
    assert send_due_reminders() == 0
    assert db.session.query(ReminderLog).count() == first


def test_cron_endpoint_requires_secret(client):
    assert client.post("/internal/cron/reminders").status_code == 403
    res = client.post("/internal/cron/reminders", headers={"X-Cron-Secret": "test-secret"})
    assert res.status_code == 200 and res.json["sent"] > 0


def test_backend_role_can_use_staff_pages(client):
    login(client, "backend.admin@example.org")
    assert client.get("/staff/matching").status_code == 200


def test_soft_answer_embedding_roundtrip(app):
    from app.models import Answer, Question

    q = db.session.query(Question).filter_by(key="mentee_hopes").one()
    assert q.pairs_with.audience == "mentor"
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    db.session.add(Answer(user_id=user.id, question_id=q.id, text="Guidance on robotics roles",
                          embedding=[0.1] * 384, embedding_model="all-MiniLM-L6-v2"))
    db.session.commit()
    db.session.expire_all()
    assert db.session.query(Answer).one().embedding[:2] == [0.1, 0.1]


def _pdf(text: str) -> bytes:
    """A one-page PDF containing `text`, enough for pypdf to extract."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def test_linkedin_import_suggests_but_does_not_save(client):
    client.post("/register", data={"role": "mentor", "name": "Linked Mentor", "email": "lm@x.org",
                                   "password": "longenough", "school": "State University"})
    pdf = _pdf("Senior PM in Software Development. Leadership, public speaking. Spanish.")
    about = {"name": "Linked Mentor", "email": "lm@x.org", "school": "State University",
             "linkedin_url": "https://www.linkedin.com/in/lm"}
    resp = client.post("/profile/1", data={**about, "linkedin_pdf": (io.BytesIO(pdf), "Profile.pdf")},
                       content_type="multipart/form-data")
    assert resp.headers["Location"].endswith("/profile/2")

    user = db.session.query(User).filter_by(email="lm@x.org").one()
    p = user.profile
    assert p.linkedin_url == "https://www.linkedin.com/in/lm"
    assert p.resume_file_name == "Profile.pdf"
    assert p.linkedin_data["source"] == "keywords"
    assert p.linkedin_data["industry"] == "Software Development"
    assert "leadership" in p.linkedin_data["tags"]["development_areas"]
    assert p.industry is None and p.development_areas == []  # suggestions only; saved by the form

    client.post("/profile/2", data={"availability": ["Monday - morning"], "languages": ["English"]})
    assert b"ring-amber-400" in client.get("/profile/3").data
    client.post("/profile/3", data={})  # reviewed and cleared: suggestions aren't pre-selected again
    assert b"ring-amber-400" not in client.get("/profile/3").data

    resp = client.post("/profile/1", data={**about, "linkedin_pdf": (io.BytesIO(b"not a pdf"), "x.pdf")},
                       content_type="multipart/form-data")
    assert resp.headers["Location"].endswith("/profile/1")


def test_admin_pages_are_admin_only(client):
    login(client, "staff.admin@example.org")
    assert client.get("/admin/").status_code == 403
    login(client, "backend.admin@example.org")
    assert client.get("/dashboard").headers["Location"].endswith("/admin/")
    staff = db.session.query(User).filter_by(email="staff.admin@example.org").one()
    mentee = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    for path in ["/admin/", "/admin/users", "/admin/users?role=staff&status=inactive&q=dana", "/admin/users/new",
                 f"/admin/users/{staff.id}", f"/admin/users/{mentee.id}", "/admin/matching-logistics",
                 "/admin/audit-logs", "/admin/profile",
                 "/staff/"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/admin/reports").status_code == 404


def test_admin_matching_logistics_and_user_match_list(client):
    staff = db.session.query(User).filter_by(email="staff.admin@example.org").one()
    accepted = Match(
        mentee_id=db.session.query(User).filter_by(email="jordan.kim@example.org").one().id,
        mentor_id=db.session.query(User).filter_by(email="priya.raman@example.org").one().id,
        status="approved", score=80, decided_by_id=staff.id,
    )
    rejected = Match(
        mentee_id=db.session.query(User).filter_by(email="avery.patel@example.org").one().id,
        mentor_id=db.session.query(User).filter_by(email="marcus.lee@example.org").one().id,
        status="rejected", score=75, decided_by_id=staff.id,
    )
    db.session.add_all((accepted, rejected))
    db.session.flush()
    db.session.add(MatchFeedback(
        match_id=rejected.id,
        author_id=staff.id,
        kind="deny",
        reason="fit_concern",
        comment="Different goals.",
    ))
    db.session.commit()

    login(client, "backend.admin@example.org")
    logistics = client.get("/admin/matching-logistics")
    assert logistics.status_code == 200
    assert b"1 / 1" in logistics.data
    assert b"Denied applicants (1)" in logistics.data
    assert rejected.mentee.name.encode() in logistics.data
    assert rejected.mentor.name.encode() in logistics.data
    assert b"Personality or fit concern" in logistics.data
    assert b"Different goals." in logistics.data

    users = client.get("/admin/users")
    assert users.status_code == 200
    assert b"Matched to" in users.data
    assert accepted.mentee.name.encode() in users.data
    assert accepted.mentor.name.encode() in users.data
    assert b"Not matched" in users.data
    assert b"Disable account" in users.data
    assert b"backend.admin@example.org" not in users.data
    live_search = client.get("/admin/users?q=jordan")
    assert b'value="jordan"' in live_search.data
    assert b'data-live-filter="admin-users"' in live_search.data
    assert b'data-sort-key="role"' in live_search.data
    assert b'data-sort-key="matched"' in live_search.data
    assert b"Attendance rate" in live_search.data
    assert b"Last access" in live_search.data
    assert b"Priya Raman" in live_search.data


def test_staff_people_search_is_live_and_table_is_sortable(client):
    login(client, "staff.admin@example.org")
    response = client.get("/staff/applications?status=all&q=jordan")
    assert response.status_code == 200
    assert b'value="jordan"' in response.data
    assert b'data-live-filter="staff-applicants"' in response.data
    assert b'data-sort-key="role"' in response.data
    assert b'data-sort-key="match"' in response.data
    assert b"Jordan Kim" in response.data


def test_login_records_last_login(client):
    login(client, "jamie.torres@example.org")
    assert db.session.query(User).filter_by(email="jamie.torres@example.org").one().last_login_at is not None


def test_admin_creates_staff_account(client):
    login(client, "backend.admin@example.org")
    client.post("/admin/users/new", data={"name": "Pat Lane", "email": "Pat@Example.org", "role": "staff",
                                          "password": "short"})
    assert not db.session.query(User).filter_by(email="pat@example.org").first()
    client.post("/admin/users/new", data={"name": "Pat Lane", "email": "Pat@Example.org", "role": "staff",
                                          "password": "temporary1"})
    assert db.session.query(User).filter_by(email="pat@example.org").one().role == "staff"
    assert db.session.query(AuditLog).filter_by(action="staff_account_created").count() == 1
    assert client.post("/admin/users/new", data={"name": "X", "email": "x@example.org", "role": "mentor",
                                                 "password": "temporary1"}).status_code == 400
    assert client.post("/admin/users/new", data={"name": "X", "email": "x@example.org", "role": "backend",
                                                 "password": "temporary1"}).status_code == 400

    login(client, "pat@example.org", "temporary1")
    assert client.get("/staff/").status_code == 200


def test_admin_user_detail_edits_account_and_overrides_match(client):
    login(client, "backend.admin@example.org")
    mentee = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    mentor = db.session.query(User).filter_by(email="priya.raman@example.org").one()
    page = client.get(f"/admin/users/{mentee.id}")
    assert page.status_code == 200
    assert b"Username" in page.data
    assert b"Matched to" in page.data
    assert b"Account Status" in page.data
    assert b"Attendance" not in page.data

    response = client.post(f"/admin/users/{mentee.id}/update", data={
        "role": "mentee", "matched_to": str(mentor.id), "status": "active",
    })
    assert response.status_code == 302
    match = db.session.query(Match).filter_by(mentee_id=mentee.id, mentor_id=mentor.id, status="released").one()
    log = db.session.query(AuditLog).filter_by(action="account_updated", target_user_id=mentee.id).one()
    assert "manual match assignment override changed" in log.description
    assert mentor.name not in log.description

    client.post(f"/admin/users/{mentee.id}/update", data={
        "role": "mentee", "matched_to": "", "status": "inactive",
    })
    assert not mentee.is_active
    assert match.status == "ended"
    assert db.session.query(AuditLog).filter_by(target_user_id=mentee.id).count() >= 2


def test_admin_requires_password_change_without_bypassing_login_password(client):
    login(client, "backend.admin@example.org")
    user = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    client.post(f"/admin/users/{user.id}/reset-password")
    assert user.must_reset_password
    assert db.session.query(AuditLog).filter_by(action="password_reset_required").count() == 1
    client.post("/logout")

    wrong = login(client, user.email, "not-the-password")
    assert b"Wrong email or password." in wrong.data
    correct = login(client, user.email)
    assert correct.headers["Location"].endswith("/password-required")
    assert client.get("/dashboard").headers["Location"].endswith("/password-required")

    invalid = client.post("/password-required", data={
        "new_password": "short", "confirm_password": "short",
    })
    assert b"at least 8 characters" in invalid.data
    valid = client.post("/password-required", data={
        "new_password": "brandnew123", "confirm_password": "brandnew123",
    })
    assert valid.status_code == 302
    assert not user.must_reset_password
    assert user.check_password("brandnew123")
    assert client.get("/dashboard").status_code == 200


def test_admin_delete_account_removes_owned_and_matched_data(client):
    login(client, "backend.admin@example.org")
    admin = db.session.query(User).filter_by(email="backend.admin@example.org").one()
    mentee = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    mentor = db.session.query(User).filter_by(email="priya.raman@example.org").one()
    match = Match(mentee_id=mentee.id, mentor_id=mentor.id, status="approved", score=75)
    db.session.add(match)
    db.session.flush()
    message = Message(match_id=match.id, sender_id=mentee.id, body="Private conversation")
    db.session.add_all([
        message,
        Attendance(event_id=1, user_id=mentee.id),
        AuditLog(actor_id=mentee.id, actor_name=mentee.name, actor_role=mentee.role,
                 target_user_id=mentee.id, action="prior_change",
                 description=f"Updated {mentee.name} ({mentee.email})."),
    ])
    user_id, match_id = mentee.id, match.id
    db.session.commit()

    page = client.get(f"/admin/users/{user_id}")
    assert b"Delete account" in page.data
    assert b"confirm(" in page.data
    response = client.post(f"/admin/users/{user_id}/delete")
    assert response.status_code == 302
    assert db.session.get(User, user_id) is None
    assert db.session.get(Match, match_id) is None
    assert db.session.query(Message).filter_by(match_id=match_id).count() == 0
    assert db.session.query(Attendance).filter_by(user_id=user_id).count() == 0
    assert db.session.query(Application).filter_by(user_id=user_id).count() == 0
    assert db.session.query(AuditLog).filter_by(action="account_deleted").count() == 1
    prior_log = db.session.query(AuditLog).filter_by(action="prior_change").one()
    assert prior_log.actor_id is None and prior_log.target_user_id is None
    assert mentee.name not in prior_log.description
    assert mentee.email not in prior_log.description
    assert prior_log.actor_name == "Deleted account"
    assert db.session.get(User, admin.id) is not None


def test_staff_applicants_have_pending_all_filters_and_sorting(client):
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").one()
    page = client.get("/staff/applications")
    assert page.status_code == 200
    assert b"Pending Approval" in page.data
    assert b"All" in page.data
    assert b"data-sort-key=\"name\"" in page.data
    assert b"data-sort-key=\"acceptance_status\"" in page.data
    assert b"Attendance_Rate" in page.data
    assert b"data-sort-select" in page.data
    assert b"Acceptance Status" in page.data
    assert b"Attendance_Rate" in page.data
    assert b"data-sort-key=\"application\"" in page.data
    assert b"data-sort-key=\"match\"" in page.data
    assert b"data-sort-key=\"submitted\"" in page.data
    assert b"Quick accept all pending" in page.data
    assert b"Other sort fields" not in page.data
    assert b'data-sort-list="staff-applicants" data-sort-select' not in page.data
    assert b"Warning: this will approve every application currently pending approval." in page.data
    assert pending.user.name.encode() in page.data
    table_headers = page.data.split(b"<thead", 1)[1].split(b"</thead>", 1)[0]
    expected_headers = [
        b">Name<", b">Role<", b">Application<", b">Attendance_Rate<",
        b">Match<", b">Submitted<", b">Acceptance Status<",
    ]
    assert [header for header in expected_headers if header in table_headers] == expected_headers
    assert table_headers.count(b"<th") == 7
    assert client.get("/staff/applications?status=all").status_code == 200
    assert client.get("/staff/applications?status=all").data.count(b"data-list-row") > 1


def test_staff_quick_accept_all_pending_applications(client):
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").all()
    assert pending
    response = client.post("/staff/applications/quick-accept")
    assert response.status_code == 302
    assert all(application.status == "accepted" for application in pending)
    assert all(application.reviewed_by_id is not None for application in pending)
    assert db.session.query(AuditLog).filter_by(action="applications_bulk_accepted").count() == 1
    assert db.session.query(Application).filter_by(status="submitted").count() == 0


def test_deactivated_account_is_signed_out_and_unmatched(client):
    mentor = db.session.query(User).filter_by(email="priya.raman@example.org").one()
    login(client, mentor.email)
    assert client.get("/dashboard").status_code == 200

    mentor.is_active = False
    db.session.commit()
    assert mentor.is_active is False
    response = client.get("/dashboard")
    assert response.status_code == 302
    login_page = client.get(response.headers["Location"])
    assert b"This account has been disabled. You have been logged out." in login_page.data
    assert b"This account has been disabled. Contact the program administrator." in login(
        client, mentor.email).data
    assert mentor.id not in matching.open_slots()

    mentor.is_active = True
    db.session.commit()
    login(client, mentor.email)
    assert client.get("/dashboard").status_code == 200


def test_admin_cannot_deactivate_self(client):
    login(client, "backend.admin@example.org")
    me = db.session.query(User).filter_by(email="backend.admin@example.org").one()
    client.post(f"/admin/users/{me.id}/active", data={"active": "0"})
    assert me.is_active


def test_admin_changes_own_password(client):
    login(client, "backend.admin@example.org")
    client.post("/admin/profile", data={"current_password": "wrong", "new_password": "newpass123",
                                        "confirm_password": "newpass123"})
    client.post("/admin/profile", data={"current_password": "password123", "new_password": "newpass123",
                                        "confirm_password": "newpass123"})
    me = db.session.query(User).filter_by(email="backend.admin@example.org").one()
    assert me.check_password("newpass123")

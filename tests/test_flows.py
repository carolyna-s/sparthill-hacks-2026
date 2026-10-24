"""HTTP flows for each role, checking what ends up in the database."""

import io

from app.extensions import db
from app.models import (Application, Attendance, Event, Match, MatchExclusion, MatchFeedback, Message,
                        ReminderLog, Submission, User)
from app.reminders import send_due_reminders

from .conftest import login


def test_healthz(client):
    assert client.get("/healthz").json == {"ok": True}


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

    blocked = client.get("/events", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/3")
    assert b"Please complete onboarding to access Events" in blocked.data

    resp = client.post("/profile/3", data={"goals": ["switch careers", "not-a-real-tag"], "goals_other": "write a book",
                                           "industry": "  software   DEVELOPMENT ", "prefers_alumni": "1"})
    assert resp.headers["Location"].endswith("/profile/4")
    assert user.profile.goals == ["switch careers"]
    assert user.profile.goals_other == "write a book"
    assert user.profile.industry == "Software Development"  # snapped to the suggestion's spelling
    assert user.profile.prefers_alumni

    blocked = client.get("/matches", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding to access Messages" in blocked.data
    blocked = client.get("/profile", follow_redirects=True)
    assert blocked.request.path.endswith("/profile/4")
    assert b"Please complete onboarding to access Profile" in blocked.data

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
    client.post("/login", data={"email": "new@x.org", "password": "longenough"})
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
    assert user.profile.languages == ["Korean"]


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

    resp = client.post("/profile/2", data={"availability": ["Friday - afternoon"]})
    assert resp.headers["Location"].endswith("/profile/2")  # language is required too
    resp = client.post("/profile/2", data={"availability": ["Friday - afternoon"], "languages": ["English"],
                                           "capacity": "3"})
    assert resp.headers["Location"].endswith("/profile/3")
    assert user.profile.capacity == 3
    client.post("/profile/3", data={})
    profile_page = client.get("/profile/4")
    assert b"Relating to your industry experience, what do you bring to the table?" in profile_page.data
    assert b"What type of mentor do you see yourself being?" in profile_page.data
    assert b"What type of advice would you give someone beginning their career in your field?" in profile_page.data


def test_staff_pages_are_staff_only(client):
    login(client, "jordan.kim@example.org")
    assert client.get("/staff/").status_code == 403
    login(client, "staff.admin@example.org")
    for path in ["/staff/", "/staff/applications", "/staff/people", "/staff/matching", "/staff/reports",
                 "/staff/events/new"]:
        assert client.get(path).status_code == 200, path


def test_review_match_and_message(client):
    login(client, "staff.admin@example.org")
    pending = db.session.query(Application).filter_by(status="submitted").one()
    client.post(f"/staff/applications/{pending.id}", data={"decision": "accepted"})
    assert pending.status == "accepted"

    client.post("/staff/matching/propose-all")
    proposed = db.session.query(Match).filter_by(status="proposed").all()
    assert len(proposed) == 5
    for m in proposed:
        client.post(f"/staff/matches/{m.id}/approve")
    match = proposed[0]
    assert match.status == "approved"

    login(client, match.mentee.email)
    client.post(f"/messages/{match.id}", data={"body": "Hi!"})
    login(client, match.mentor.email)
    page = client.get(f"/messages/{match.id}")
    assert b"Hi!" in page.data
    assert db.session.query(Message).one().read_at is not None

    outsider = next(m for m in proposed if not m.includes(match.mentor))
    assert client.get(f"/messages/{outsider.id}").status_code == 404


def test_reject_match_needs_reason_and_is_never_reproposed(client):
    login(client, "staff.admin@example.org")
    client.post("/staff/matching/propose-all")
    m = db.session.query(Match).filter_by(status="proposed").first()
    assert client.get(f"/staff/matches/{m.id}").status_code == 200

    client.post(f"/staff/matches/{m.id}/reject")  # no reason or explanation
    client.post(f"/staff/matches/{m.id}/reject", data={"reason": "gut_feeling", "comment": "  "})
    assert m.status == "proposed" and db.session.query(MatchFeedback).count() == 0

    client.post(f"/staff/matches/{m.id}/reject",
                data={"reason": "gut_feeling", "comment": "Their goals don't line up, I just sense it."})
    assert m.status == "rejected"
    f = db.session.query(MatchFeedback).one()
    assert (f.kind, f.reason, f.comment) == ("deny", "gut_feeling", "Their goals don't line up, I just sense it.")
    assert db.session.query(MatchExclusion).filter_by(mentee_id=m.mentee_id, mentor_id=m.mentor_id).count() == 1

    client.post("/staff/matching/propose-all")
    assert db.session.query(Match).filter_by(mentee_id=m.mentee_id, mentor_id=m.mentor_id).count() == 1
    assert b"I just sense it" in client.get("/staff/matching").data
    assert b"I just sense it" in client.get(f"/staff/people/{m.mentee_id}").data


def test_staff_people_dashboards(client):
    login(client, "staff.admin@example.org")
    page = client.get("/staff/people?role=mentee&q=jordan").data
    assert b"Jordan Kim" in page and b"Priya Raman" not in page
    jordan = db.session.query(User).filter_by(email="jordan.kim@example.org").one()
    assert client.get(f"/staff/people/{jordan.id}").status_code == 200
    staff = db.session.query(User).filter_by(role="staff").first()
    assert client.get(f"/staff/people/{staff.id}").status_code == 404
    login(client, "jordan.kim@example.org")
    assert client.get("/staff/people").status_code == 403


def test_event_submission_checkin_feedback(client):
    event = db.session.query(Event).first()
    login(client, "jordan.kim@example.org")
    client.post(f"/events/{event.id}/submit/prework",
                data={"body": "my goals", "file": (io.BytesIO(b"pdf"), "goals.pdf")},
                content_type="multipart/form-data")
    sub = db.session.query(Submission).one()
    assert sub.file_name == "goals.pdf"
    assert client.get(f"/submissions/{sub.id}/file").data == b"pdf"

    client.post(f"/events/{event.id}/checkin", data={"code": "wrong"})
    assert db.session.query(Attendance).count() == 0
    client.post(f"/events/{event.id}/checkin", data={"code": event.checkin_code.lower()})
    assert db.session.query(Attendance).count() == 1

    client.post("/feedback", data={"event_id": event.id, "rating": 4})
    login(client, "staff.admin@example.org")
    assert b"4.0" in client.get("/staff/reports").data


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

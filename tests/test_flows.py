"""HTTP flows for each role, checking what ends up in the database."""

import io

from app.extensions import db
from app.models import Application, Attendance, Event, Match, Message, ReminderLog, Submission, User
from app.reminders import send_due_reminders

from .conftest import login


def test_healthz(client):
    assert client.get("/healthz").json == {"ok": True}


def test_mentee_intake_flow(client):
    client.post("/register", data={"role": "mentee", "name": "New Person", "email": "new@x.org",
                                   "password": "longenough", "school": "State University"})
    client.post("/profile", data={"goals": ["switch careers", "not-a-real-tag"], "goals_other": "write a book",
                                  "industry": "  software   DEVELOPMENT ", "looking_for": "Interview practice"})
    user = db.session.query(User).filter_by(email="new@x.org").one()
    assert user.profile.school == "State University"
    assert user.profile.goals == ["switch careers"]
    assert user.profile.goals_other == "write a book"
    assert user.profile.industry == "Software Development"  # snapped to the suggestion's spelling
    assert user.profile.looking_for == "Interview practice"

    answers = {"why": "a", "success": "b", "commitment": "4"}
    client.post("/apply", data={**answers, "action": "submit"})
    assert user.application.status == "draft"  # agreement not signed yet

    agreement_id = 1
    client.post(f"/agreements/{agreement_id}/sign", data={"typed_name": "New Person"})
    client.post("/apply", data={**answers, "action": "submit"})
    assert user.application.status == "draft"  # no availability or language yet

    resp = client.post("/profile", data={"availability": ["Monday - morning", "Funday - noon"],
                                         "languages": ["Spanish"], "industry": "Marine Robotics",
                                         "prefers_alumni": "1"})
    assert resp.headers["Location"].endswith("/apply")
    assert user.profile.availability == ["Monday - morning"]
    assert user.profile.industry == "Marine Robotics"  # not a suggestion: kept as typed
    assert user.profile.prefers_alumni

    client.post("/apply", data={**answers, "action": "submit"})
    db.session.refresh(user.application)
    assert user.application.status == "submitted"


def test_register_requires_school(client):
    client.post("/register", data={"role": "mentee", "name": "No School", "email": "ns@x.org",
                                   "password": "longenough", "school": "  "})
    assert db.session.query(User).filter_by(email="ns@x.org").first() is None


def test_profile_requires_availability_not_language(client):
    client.post("/register", data={"role": "mentor", "name": "New Mentor", "email": "nm@x.org",
                                   "password": "longenough", "school": "City College"})
    resp = client.post("/profile", data={})
    assert resp.headers["Location"].endswith("/profile")  # availability missing: stay on the form

    resp = client.post("/profile", data={"availability": ["Friday - afternoon"]})
    assert resp.headers["Location"].endswith("/apply")  # language is optional
    user = db.session.query(User).filter_by(email="nm@x.org").one()
    assert user.profile.languages == ["English"]


def test_staff_pages_are_staff_only(client):
    login(client, "jordan.kim@example.org")
    assert client.get("/staff/").status_code == 403
    login(client, "staff.admin@example.org")
    for path in ["/staff/", "/staff/applications", "/staff/matching", "/staff/reports", "/staff/events/new"]:
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

"""Demo data: `flask --app wsgi seed`. Every account's password is `password123`."""

from __future__ import annotations

from datetime import date, timedelta

from .extensions import db
from .models import (Agreement, AgreementSignature, Application, Cohort, Event, Profile, User,
                     utcnow)

PASSWORD = "password123"

MENTORS = [
    ("Priya Raman", "Staff engineer", ["software engineering", "entrepreneurship"],
     ["get promoted", "lead a team", "switch careers"], ["technical skills", "leadership", "negotiation"], 2),
    ("Marcus Lee", "Product lead", ["product management", "design", "consulting"],
     ["switch careers", "build a network"], ["public speaking", "networking", "confidence"], 2),
    ("Elena Ortiz", "Data science manager", ["data science", "research", "healthcare"],
     ["apply to grad school", "land first job"], ["technical skills", "writing", "resume and interviewing"], 1),
    ("Sam Okafor", "Nonprofit director", ["nonprofit", "public policy", "education"],
     ["find a niche", "start a business"], ["leadership", "time management", "work-life balance"], 1),
]

MENTEES = [
    ("Jordan Kim", ["software engineering", "data science"], ["land first job"],
     ["resume and interviewing", "technical skills"]),
    ("Avery Patel", ["product management", "design"], ["switch careers", "build a network"],
     ["networking", "confidence"]),
    ("Riley Chen", ["public policy", "nonprofit"], ["find a niche"], ["leadership", "public speaking"]),
    ("Taylor Brooks", ["data science", "healthcare"], ["apply to grad school"], ["writing", "technical skills"]),
    ("Morgan Diaz", ["entrepreneurship", "software engineering"], ["start a business", "lead a team"],
     ["leadership", "negotiation"]),
]


def _user(name: str, role: str) -> User:
    email = name.lower().replace(" ", ".") + "@example.org"
    u = db.session.query(User).filter_by(email=email).first()
    if u:
        return u
    u = User(email=email, name=name, role=role)
    u.set_password(PASSWORD)
    db.session.add(u)
    return u


def seed() -> None:
    db.create_all()
    if db.session.query(Cohort).first():
        return  # already seeded

    cohort = Cohort(name="Fall 2026", starts_on=date.today(), ends_on=date.today() + timedelta(days=90))
    agreement = Agreement(title="Program Participation Agreement", version="2026-10-v1", audience="all",
                          body="I agree to attend scheduled sessions, complete prework and postwork, "
                               "communicate respectfully, and keep mentor-mentee conversations confidential.")
    db.session.add_all([cohort, agreement])
    _user("Staff Admin", "staff")
    db.session.flush()

    for name, headline, interests, goals, areas, cap in MENTORS:
        u = _user(name, "mentor")
        u.profile = Profile(headline=headline, career_interests=interests, goals=goals,
                            development_areas=areas, capacity=cap)
        u.application = Application(cohort_id=cohort.id, status="accepted", submitted_at=utcnow(),
                                    answers={"experience": "10+ years", "why": "Give back", "commitment": "4"})
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))

    for i, (name, interests, goals, areas) in enumerate(MENTEES):
        u = _user(name, "mentee")
        u.profile = Profile(career_interests=interests, goals=goals, development_areas=areas)
        # Leave the last mentee pending so the review queue has something in it.
        status = "submitted" if i == len(MENTEES) - 1 else "accepted"
        u.application = Application(cohort_id=cohort.id, status=status, submitted_at=utcnow(),
                                    answers={"why": "Grow my career", "success": "A clear plan", "commitment": "4"})
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))

    now = utcnow().replace(minute=0, second=0, microsecond=0)
    db.session.add_all([
        Event(cohort_id=cohort.id, title="Kickoff: Setting Goals", starts_at=now + timedelta(days=2),
              location="Zoom", checkin_code="KICK01",
              prework_prompt="Write down three things you want out of this program.",
              prework_due=now + timedelta(days=1, hours=12),
              postwork_prompt="Share your 90-day goal with your mentor and summarize their feedback.",
              postwork_due=now + timedelta(days=9)),
        Event(cohort_id=cohort.id, title="Networking Workshop", starts_at=now + timedelta(days=16),
              location="Community Center, Room 2", checkin_code="NET02",
              prework_prompt="Draft a 30-second introduction.", prework_due=now + timedelta(days=15)),
    ])
    db.session.commit()

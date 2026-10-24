"""Demo data: `flask --app wsgi seed`. Every account's password is `password123`."""

from __future__ import annotations

from datetime import date, timedelta

from .extensions import db
from .models import (Agreement, AgreementSignature, Application, Cohort, Event, MatchingConfig, Profile,
                     Question, User, utcnow)

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


# Sign-up form answers (hard + soft filters), by name. Jordan only shares a time slot with
# Priya and Elena, so the hard filter is visible on the staff matching page.
MATCHING = {
    "Priya Raman": dict(availability=["Monday - afternoon", "Wednesday - afternoon"], languages=["English", "Hindi"],
                        industry="Software Development", education_paths=["4-year university", "graduate degree"],
                        school="State University", looking_for="Help early-career engineers grow into senior roles."),
    "Marcus Lee": dict(availability=["Tuesday - morning", "Thursday - morning", "Saturday - morning"],
                       languages=["English", "Mandarin"], industry="Technology, Information and Internet",
                       education_paths=["4-year university"], school="Tech Institute",
                       looking_for="Practice for product interviews and introductions to PMs I know."),
    "Elena Ortiz": dict(availability=["Monday - morning", "Wednesday - morning", "Friday - afternoon"],
                        languages=["English", "Spanish"], industry="Data Infrastructure and Analytics",
                        education_paths=["graduate degree", "first-generation college student"], school="State University",
                        looking_for="Guidance on grad school applications and breaking into data science."),
    "Sam Okafor": dict(availability=["Saturday - morning", "Sunday - afternoon", "Tuesday - afternoon"],
                       languages=["English", "Spanish"], industry="Non-profit Organizations",
                       education_paths=["community college transfer", "first-generation college student"],
                       school="City College", looking_for="A sounding board for mission-driven careers."),
    "Jordan Kim": dict(availability=["Monday - afternoon", "Friday - afternoon"], languages=["English", "Korean"],
                       industry="Software Development", education_paths=["4-year university"],
                       school="State University", prefers_alumni=True,
                       looking_for="Someone to review my resume and do mock technical interviews."),
    "Avery Patel": dict(availability=["Tuesday - morning", "Thursday - morning"], languages=["English"],
                        industry="Technology, Information and Internet", education_paths=["4-year university"],
                        school="State University", goals_other="move from design into product",
                        looking_for="Advice on switching from design to product management."),
    "Riley Chen": dict(availability=["Saturday - morning", "Tuesday - afternoon"], languages=["English", "Cantonese"],
                       industry="Non-profit Organizations", education_paths=["community college transfer"],
                       school="State University", looking_for="Figuring out which policy or nonprofit path fits me."),
    "Taylor Brooks": dict(availability=["Wednesday - morning", "Friday - afternoon"], languages=["English", "Spanish"],
                          industry="Data Infrastructure and Analytics", education_paths=["first-generation college student"],
                          school="State University", prefers_alumni=True,
                          looking_for="Help choosing grad programs in health data science."),
    "Morgan Diaz": dict(availability=["Monday - afternoon", "Saturday - morning"], languages=["English", "Spanish"],
                        industry="Software Development", education_paths=["4-year university"], school="State University",
                        looking_for="Accountability while I build my first startup."),
}

DEFAULT_WEIGHTS = {"pathways": 0.15, "interests": 0.15, "major": 0.10, "years_experience": 0.10,
                   "languages": 0.10, "clubs": 0.10, "student_groups": 0.10, "goals": 0.10,
                   "organizations": 0.05, "concentration": 0.05}
DEFAULT_SETTINGS = {"alpha": 0.6, "experience_gap": [3, 10], "load_penalty": 0.1,
                    "context_range": [0.85, 1.15], "llm_top_k": 5}

# Soft (free-text) questions, as (mentee key, mentee prompt, mentor key, mentor prompt).
SOFT_QUESTIONS = [
    ("mentee_hopes", "What do you hope to get out of having a mentor?",
     "mentor_offers", "What do you hope to offer a mentee?"),
    ("mentee_path", "Where do you see yourself in 3-5 years, and what's in the way?",
     "mentor_path", "Describe your career path, including detours."),
    ("mentee_style", "How do you like to receive advice and feedback?",
     "mentor_style", "Describe your mentoring or communication style."),
]


def _questions() -> None:
    for i, (ek, ep, rk, rp) in enumerate(SOFT_QUESTIONS):
        mentor_q = Question(key=rk, audience="mentor", prompt=rp, sort=i)
        db.session.add(mentor_q)
        db.session.flush()
        db.session.add(Question(key=ek, audience="mentee", prompt=ep, sort=i, pairs_with_id=mentor_q.id))


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
    _user("Backend Admin", "backend")
    db.session.add(MatchingConfig(is_active=True, weights=DEFAULT_WEIGHTS, settings=DEFAULT_SETTINGS,
                                  notes="Initial weights from docs/PLAN.md"))
    _questions()
    db.session.flush()

    for name, headline, interests, goals, areas, cap in MENTORS:
        u = _user(name, "mentor")
        u.profile = Profile(headline=headline, interests=", ".join(interests), goals=goals,
                            development_areas=areas, capacity=cap, **MATCHING[name])
        u.application = Application(cohort_id=cohort.id, status="accepted", submitted_at=utcnow(),
                                    answers={"experience": "10+ years", "why": "Give back", "commitment": "4"})
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))

    for i, (name, interests, goals, areas) in enumerate(MENTEES):
        u = _user(name, "mentee")
        u.profile = Profile(interests=", ".join(interests), goals=goals, development_areas=areas, **MATCHING[name])
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

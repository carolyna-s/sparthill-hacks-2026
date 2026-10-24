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

# Extra accepted, unmatched people for trying out "Run matching": `flask --app wsgi seed-pool`.
# Sofia fits Nadia best, Noor fits Grace, and Ethan shares a slot with all three mentors but
# fits Diego, so the solver has to weigh the whole pool rather than each mentee's top pick.
POOL_MENTORS = [
    ("Nadia Haddad", "UX research lead", ["design", "research", "healthcare"],
     ["switch careers", "land first job"], ["confidence", "public speaking", "writing"],
     dict(availability=["Tuesday - afternoon", "Thursday - afternoon", "Sunday - afternoon"],
          languages=["English", "Arabic"], industry="Design Services", education_paths=["4-year university"],
          school="State University", looking_for="Help career changers find their footing in UX.")),
    ("Diego Alvarez", "Startup founder", ["entrepreneurship", "consulting", "software engineering"],
     ["start a business", "build a network"], ["negotiation", "networking", "leadership"],
     dict(availability=["Wednesday - evening", "Thursday - afternoon"], languages=["English", "Spanish"],
          industry="Software Development", education_paths=["bootcamp / self-taught"], school="City College",
          looking_for="Founders who want honest feedback on early ideas.")),
    ("Grace Liu", "Policy analyst", ["public policy", "research", "education"],
     ["apply to grad school", "find a niche"], ["writing", "time management", "resume and interviewing"],
     dict(availability=["Sunday - afternoon", "Wednesday - evening"], languages=["English", "Mandarin"],
          industry="Government Administration", education_paths=["graduate degree", "first-generation college student"],
          school="State University", looking_for="Students weighing a policy master's or PhD.")),
]

POOL_MENTEES = [
    ("Sofia Ramirez", ["design", "healthcare"], ["switch careers"], ["confidence", "public speaking"],
     dict(availability=["Tuesday - afternoon", "Sunday - afternoon"], languages=["English", "Spanish"],
          industry="Hospitals and Health Care", education_paths=["returning / adult learner"],
          school="State University", looking_for="Moving from nursing into health-tech design.")),
    ("Ethan Walker", ["entrepreneurship", "software engineering"], ["start a business", "build a network"],
     ["negotiation", "networking"],
     dict(availability=["Wednesday - evening", "Thursday - afternoon", "Sunday - afternoon"], languages=["English"],
          industry="Software Development", education_paths=["bootcamp / self-taught"], school="City College",
          looking_for="Someone who has raised money and can pressure-test my pitch.")),
    ("Noor Ahmed", ["public policy", "education"], ["apply to grad school"], ["writing", "time management"],
     dict(availability=["Sunday - afternoon"], languages=["English", "Arabic"], industry="Higher Education",
          education_paths=["first-generation college student"], school="State University",
          looking_for="Choosing between MPP programs and writing my statement.")),
]

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


def _activity(reviewer: User) -> None:
    """Spread out sign-up and login times and mark accepted applications reviewed, so the
    admin pages have history to show. Jamie Torres and Morgan Diaz have never logged in."""
    now = utcnow()
    for i, u in enumerate(db.session.query(User).order_by(User.id)):
        u.created_at = now - timedelta(days=30 - 2 * i)
        if u.email not in ("jamie.torres@example.org", "morgan.diaz@example.org"):
            u.last_login_at = now - timedelta(hours=5 * i + 1)
            u.last_seen_at = u.last_login_at + timedelta(minutes=20)
        if u.application and u.application.status == "accepted":
            u.application.reviewed_by_id, u.application.reviewed_at = reviewer.id, now - timedelta(days=3)


def seed_pool() -> int:
    """Add POOL_MENTORS and POOL_MENTEES as accepted and unmatched. Needs `seed` first.
    Skips anyone already there; returns how many were added."""
    cohort = db.session.query(Cohort).order_by(Cohort.id).first()
    agreement = db.session.query(Agreement).order_by(Agreement.id).first()
    if not cohort or not agreement:
        raise RuntimeError("run `flask seed` first")
    people = ([(n, "mentor", dict(headline=h, interests=", ".join(i), goals=g, development_areas=a, **m))
               for n, h, i, g, a, m in POOL_MENTORS]
              + [(n, "mentee", dict(interests=", ".join(i), goals=g, development_areas=a, **m))
                 for n, i, g, a, m in POOL_MENTEES])
    added = 0
    for name, role, profile in people:
        u = _user(name, role)
        if u.application:
            continue
        u.profile = Profile(**profile)
        u.application = Application(cohort_id=cohort.id, status="accepted", submitted_at=utcnow(),
                                    reviewed_at=utcnow(), answers={})
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))
        added += 1
    db.session.commit()
    return added


def seed() -> None:
    db.create_all()
    if db.session.query(Cohort).first():
        return  # already seeded

    cohort = Cohort(name="Fall 2026", starts_on=date.today(), ends_on=date.today() + timedelta(days=90))
    agreement = Agreement(title="Program Participation Agreement", version="2026-10-v1", audience="all",
                          body="I agree to attend scheduled sessions, complete prework and postwork, "
                               "communicate respectfully, and keep mentor-mentee conversations confidential.")
    db.session.add_all([cohort, agreement])
    staff = _user("Staff Admin", "staff")
    _user("Backend Admin", "backend")
    _user("Jamie Torres", "staff")  # never logged in
    _user("Dana Whitfield", "staff").is_active = False
    db.session.add(MatchingConfig(is_active=True, weights=DEFAULT_WEIGHTS, settings=DEFAULT_SETTINGS,
                                  notes="Initial weights from docs/PLAN.md"))
    _questions()
    db.session.flush()

    for name, headline, interests, goals, areas, cap in MENTORS:
        u = _user(name, "mentor")
        u.profile = Profile(headline=headline, interests=", ".join(interests), goals=goals,
                            development_areas=areas, capacity=cap, **MATCHING[name])
        u.application = Application(cohort_id=cohort.id, status="accepted", submitted_at=utcnow(),
                                    answers={
                                        "mentorship_style": "A supportive mentor who shares practical experience.",
                                        "career_advice": "Build strong fundamentals and seek feedback early.",
                                    })
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))

    for i, (name, interests, goals, areas) in enumerate(MENTEES):
        u = _user(name, "mentee")
        u.profile = Profile(interests=", ".join(interests), goals=goals, development_areas=areas, **MATCHING[name])
        # Leave the last mentee pending so the review queue has something in it.
        status = "submitted" if i == len(MENTEES) - 1 else "accepted"
        u.application = Application(cohort_id=cohort.id, status=status, submitted_at=utcnow(),
                                    answers={
                                        "mentorship_style": "Clear communication and actionable feedback.",
                                        "career_advice": "How to choose opportunities that build my skills.",
                                    })
        db.session.flush()
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=u.id, typed_name=name))

    db.session.flush()
    _activity(staff)

    now = utcnow().replace(minute=0, second=0, microsecond=0)
    db.session.add(Event(
        cohort_id=cohort.id, title="Updating your Resume", starts_at=now + timedelta(days=3),
        location="Zoom", checkin_code="RES01",
        description="Turn your resume into a one-page story of your strongest work, then review it with your mentor.",
        prework_prompt="Upload your current resume and list two roles you'd like to apply for.",
        prework_due=now + timedelta(days=1, hours=12),
        postwork_prompt="Upload your revised resume and note the top three changes your mentor suggested.",
        postwork_due=now + timedelta(days=10)))
    db.session.commit()

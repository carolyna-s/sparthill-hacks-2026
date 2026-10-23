"""Database tables. See docs/SCHEMA.md for what each one is for.

Works on SQLite (local) and Postgres (RDS). List-valued fields use the JSON type, which
both support.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

ROLES = ("mentee", "mentor", "staff")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- people ----------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # mentee | mentor | staff
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    profile = db.relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    application = db.relationship("Application", back_populates="user", uselist=False,
                                  cascade="all, delete-orphan", foreign_keys="Application.user_id")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_staff(self) -> bool:
        return self.role == "staff"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


class Profile(db.Model):
    """One per mentor or mentee. Tag fields come from app/taxonomy.py.

    For mentees, `development_areas` are what they want to grow in; for mentors, they're
    what the mentor can coach. `goals` works the same way.
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    headline = db.Column(db.String(200), default="")
    bio = db.Column(db.Text, default="")
    organization = db.Column(db.String(200), default="")
    career_interests = db.Column(db.JSON, default=list, nullable=False)
    goals = db.Column(db.JSON, default=list, nullable=False)
    development_areas = db.Column(db.JSON, default=list, nullable=False)
    capacity = db.Column(db.Integer, default=1, nullable=False)  # mentors: max active mentees
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="profile")


# --- intake ----------------------------------------------------------------

class Cohort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class Application(db.Model):
    STATUSES = ("draft", "submitted", "accepted", "waitlisted", "rejected")

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))
    status = db.Column(db.String(12), default="draft", nullable=False, index=True)
    answers = db.Column(db.JSON, default=dict, nullable=False)  # {question_key: text}
    submitted_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    staff_notes = db.Column(db.Text, default="")

    user = db.relationship("User", back_populates="application", foreign_keys=[user_id])
    cohort = db.relationship("Cohort")


class Agreement(db.Model):
    """A versioned agreement text. Publishing a new version means adding a row."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(40), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(10), default="all", nullable=False)  # mentee | mentor | all
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class AgreementSignature(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    agreement_id = db.Column(db.Integer, db.ForeignKey("agreement.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    typed_name = db.Column(db.String(120), nullable=False)
    signed_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    ip_address = db.Column(db.String(64))

    agreement = db.relationship("Agreement")
    __table_args__ = (db.UniqueConstraint("agreement_id", "user_id"),)


# --- matching --------------------------------------------------------------

class Match(db.Model):
    STATUSES = ("proposed", "approved", "rejected", "ended")

    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))
    status = db.Column(db.String(10), default="proposed", nullable=False, index=True)
    score = db.Column(db.Float, nullable=False)
    score_breakdown = db.Column(db.JSON, default=dict, nullable=False)
    proposed_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    decided_at = db.Column(db.DateTime)

    mentee = db.relationship("User", foreign_keys=[mentee_id])
    mentor = db.relationship("User", foreign_keys=[mentor_id])

    def other(self, user: User) -> User:
        return self.mentor if user.id == self.mentee_id else self.mentee

    def includes(self, user: User) -> bool:
        return user.id in (self.mentee_id, self.mentor_id)


# --- program tools ---------------------------------------------------------

class Event(db.Model):
    """A program session (workshop, meeting) with optional prework and postwork."""

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    starts_at = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200), default="")
    checkin_code = db.Column(db.String(12), nullable=False)
    prework_prompt = db.Column(db.Text, default="")
    prework_due = db.Column(db.DateTime)
    postwork_prompt = db.Column(db.Text, default="")
    postwork_due = db.Column(db.DateTime)

    cohort = db.relationship("Cohort")


class Submission(db.Model):
    KINDS = ("prework", "postwork")

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    body = db.Column(db.Text, default="")
    file_key = db.Column(db.String(500))  # S3 key or local path under UPLOAD_DIR
    file_name = db.Column(db.String(255))
    submitted_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("event_id", "user_id", "kind"),)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    checked_in_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("event_id", "user_id"),)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    read_at = db.Column(db.DateTime)

    sender = db.relationship("User")


class Feedback(db.Model):
    """Satisfaction rating (1-5) for an event or for a match."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"))
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ReminderLog(db.Model):
    """One row per reminder sent, so the scheduler never sends the same one twice."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    key = db.Column(db.String(120), nullable=False)  # e.g. "prework:12", "agreement:3"
    sent_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "key"),)

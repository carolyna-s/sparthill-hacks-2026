"""Database tables. See docs/SCHEMA.md for what each one is for.

Works on SQLite (local, tests) and Postgres (Supabase). List-valued fields use JSON, which
both support; embeddings use `Embedding`, which is pgvector on Postgres and JSON on SQLite.

Matching inputs come in two kinds (docs/PLAN.md §4):
- hard questions: dropdown / multiple-choice answers, stored as typed Profile columns, used
  for filtering and the structured score
- soft questions: free-text answers (Question/Answer), embedded for the semantic score
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .types import Embedding

ROLES = ("mentee", "mentor", "staff", "backend")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- people ----------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # mentee | mentor | staff | backend
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
        """Staff pages are open to backend admins too."""
        return self.role in ("staff", "backend")

    @property
    def is_backend(self) -> bool:
        return self.role == "backend"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


def _tags():
    """A JSON list column that defaults to [] (server default too, so adding it to a table
    with existing rows works)."""
    return db.Column(db.JSON, default=list, server_default="[]", nullable=False)


class Profile(db.Model):
    """One per mentor or mentee: the answers to the hard (dropdown) questions.

    Tag values come from taxonomy_term. For mentees, list fields mean what they want; for
    mentors, what they have or offer (e.g. `pathways`: mentee's target vs mentor's actual).
    """

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    headline = db.Column(db.String(200), default="")
    bio = db.Column(db.Text, default="")
    organization = db.Column(db.String(200), default="")
    career_interests = db.Column(db.JSON, default=list, nullable=False)  # legacy; replaced by `industry`
    goals = db.Column(db.JSON, default=list, nullable=False)
    development_areas = db.Column(db.JSON, default=list, nullable=False)
    capacity = db.Column(db.Integer, default=1, nullable=False)  # mentors: max active mentees

    major = db.Column(db.String(120))
    concentration = db.Column(db.String(120))
    pathways = _tags()
    years_experience = db.Column(db.Integer)
    languages = _tags()
    language_required = db.Column(db.Boolean, default=False, server_default=db.false(), nullable=False)
    organizations = _tags()  # mentee: target orgs; mentor: current/past employers
    clubs_prior = _tags()
    clubs_current = _tags()
    student_groups = _tags()  # sensitive: never shown to the other party
    groups_opt_in = db.Column(db.Boolean, default=False, server_default=db.false(), nullable=False)
    # Sign-up matching form (app/taxonomy.py). Hard filters: availability, languages.
    availability = _tags()  # "Monday - morning", ...
    # Soft filters, alongside goals / development_areas above.
    industry = db.Column(db.String(120))  # taxonomy.INDUSTRIES value, or whatever the user typed
    education_paths = _tags()
    school = db.Column(db.String(200))  # asked at sign-up. mentee: current school; mentor: alma mater
    prefers_alumni = db.Column(db.Boolean, default=False, server_default=db.false(), nullable=False)
    # Free-text answers: shown to staff, not scored yet (semantic score, docs/PLAN.md §4.4).
    interests = db.Column(db.Text)
    goals_other = db.Column(db.Text)  # goals beyond the presets
    looking_for = db.Column(db.Text)  # mentee: wants from the program; mentor: hopes to offer
    linkedin_url = db.Column(db.String(300))
    resume_key = db.Column(db.String(500))  # storage key of the uploaded resume / LinkedIn PDF
    resume_file_name = db.Column(db.String(255))

    # Combined embedding of all soft answers, for one-shot nearest-neighbor lookups.
    embedding = db.Column(Embedding())
    embedding_model = db.Column(db.String(80))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="profile")


# --- intake ----------------------------------------------------------------

class Cohort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Cycle (docs/PLAN.md §3): signup -> matching -> review -> released -> closed
    phase = db.Column(db.String(10), default="signup", server_default="signup", nullable=False)
    signup_opens = db.Column(db.DateTime)
    signup_closes = db.Column(db.DateTime)
    review_deadline = db.Column(db.DateTime)
    confirm_days = db.Column(db.Integer, default=7, server_default="7", nullable=False)
    matched_at = db.Column(db.DateTime)
    released_at = db.Column(db.DateTime)


class Application(db.Model):
    STATUSES = ("draft", "submitted", "accepted", "waitlisted", "rejected", "withdrawn")

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
    """A proposed or approved pair.

    proposed -> approved | rejected (staff deny)
    approved -> withdrawn (mentee withdraws after release) | ended
    Scores are 0-100: final = (alpha*structured + (1-alpha)*semantic) * context_multiplier.
    """

    STATUSES = ("proposed", "approved", "rejected", "withdrawn", "ended")

    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))
    status = db.Column(db.String(10), default="proposed", nullable=False, index=True)
    score = db.Column(db.Float, nullable=False)  # final score shown to staff
    score_breakdown = db.Column(db.JSON, default=dict, nullable=False)
    structured_score = db.Column(db.Float)  # hard-question features
    semantic_score = db.Column(db.Float)  # soft-answer embedding similarity
    context_multiplier = db.Column(db.Float)  # LLM context scaling, e.g. 0.85-1.15
    ai_review = db.Column(db.JSON)  # {note, flags, confidence, feedback_ids_used}
    config_id = db.Column(db.Integer, db.ForeignKey("matching_config.id"))
    rematch_round = db.Column(db.Integer, default=1, server_default="1", nullable=False)
    proposed_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    decided_at = db.Column(db.DateTime)
    # After release: the mentee confirms they're still in, or withdraws.
    released_at = db.Column(db.DateTime)
    confirm_by = db.Column(db.DateTime)
    mentee_confirmed_at = db.Column(db.DateTime)
    withdrawn_at = db.Column(db.DateTime)

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


# --- configuration (edited by backend users) -------------------------------

class TaxonomyTerm(db.Model):
    """Dropdown options for the hard questions.

    kind: major | concentration | pathway | interest | goal | development_area | language |
          organization | club | student_group
    `parent_id` scopes concentrations and pathways to a major; `group` holds a major's field
    group (STEM, Business, ...) or a club's category, used for partial-credit matches.
    """

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    value = db.Column(db.String(120), nullable=False)
    group = db.Column(db.String(80))
    parent_id = db.Column(db.Integer, db.ForeignKey("taxonomy_term.id"))
    sort = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    is_active = db.Column(db.Boolean, default=True, server_default=db.true(), nullable=False)

    parent = db.relationship("TaxonomyTerm", remote_side=[id])
    __table_args__ = (db.UniqueConstraint("kind", "value", "parent_id"),)


class Question(db.Model):
    """A soft (free-text) question whose answers are embedded for semantic matching.

    `pairs_with_id` links a mentee question to the mentor question it's compared against,
    e.g. "What do you hope to get from a mentor?" <-> "What do you offer as a mentor?".
    """

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(60), unique=True, nullable=False)
    audience = db.Column(db.String(10), nullable=False)  # mentee | mentor
    prompt = db.Column(db.Text, nullable=False)
    help_text = db.Column(db.Text, default="")
    pairs_with_id = db.Column(db.Integer, db.ForeignKey("question.id"))
    weight = db.Column(db.Float, default=1.0, server_default="1", nullable=False)
    required = db.Column(db.Boolean, default=True, server_default=db.true(), nullable=False)
    sort = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    is_active = db.Column(db.Boolean, default=True, server_default=db.true(), nullable=False)

    pairs_with = db.relationship("Question", remote_side=[id])


class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    embedding = db.Column(Embedding())  # null until the embedding job runs
    embedding_model = db.Column(db.String(80))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    question = db.relationship("Question")
    __table_args__ = (db.UniqueConstraint("user_id", "question_id"),)


class MatchingConfig(db.Model):
    """A versioned weight set. Exactly one is active; every Match records the one it used.

    weights:  {feature: weight} for the structured score
    settings: {"alpha": 0.6, "experience_gap": [3, 10], "load_penalty": 0.1,
               "context_range": [0.85, 1.15], "llm_top_k": 5}
    """

    id = db.Column(db.Integer, primary_key=True)
    weights = db.Column(db.JSON, nullable=False)
    settings = db.Column(db.JSON, default=dict, nullable=False)
    is_active = db.Column(db.Boolean, default=False, server_default=db.false(), nullable=False)
    source = db.Column(db.String(12), default="manual", server_default="manual", nullable=False)  # manual | ai
    notes = db.Column(db.Text, default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ConfigSuggestion(db.Model):
    """A change the LLM proposes after reading staff/mentee feedback. A backend user applies
    it (creating a new MatchingConfig) or dismisses it."""

    id = db.Column(db.Integer, primary_key=True)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))
    based_on_config_id = db.Column(db.Integer, db.ForeignKey("matching_config.id"), nullable=False)
    proposed_weights = db.Column(db.JSON)
    proposed_settings = db.Column(db.JSON)
    rules = db.Column(db.JSON, default=list, nullable=False)  # plain-language rules, e.g. pathway equivalences
    rationale = db.Column(db.Text, nullable=False)
    evidence_feedback_ids = db.Column(db.JSON, default=list, nullable=False)
    status = db.Column(db.String(10), default="pending", server_default="pending", nullable=False)  # pending | applied | dismissed
    decided_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    decided_at = db.Column(db.DateTime)
    applied_config_id = db.Column(db.Integer, db.ForeignKey("matching_config.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# --- match feedback loop ---------------------------------------------------

class MatchFeedback(db.Model):
    """Feedback the matching LLM learns from.

    kind: deny (staff denies a proposal) | withdraw (mentee leaves after release) |
          confirm (mentee confirms, optional note) | check_in (later pulse)
    The comment is embedded so similar past feedback can be retrieved for new pairs.
    """

    REASONS = {
        "deny": ("interests_or_pathway", "experience_gap", "language_or_communication", "fit_concern",
                 "mentor_overloaded", "conflict_of_interest", "other"),
        "withdraw": ("no_time", "not_a_good_fit", "found_other_mentorship", "program_not_for_me", "other"),
    }

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(40))
    comment = db.Column(db.Text, default="")
    wants_rematch = db.Column(db.Boolean)  # withdraw only: re-enter matching vs leave the program
    embedding = db.Column(Embedding())
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    match = db.relationship("Match")
    author = db.relationship("User")


class MatchExclusion(db.Model):
    """Pairs never to propose again (from a deny or a not-a-good-fit withdrawal)."""

    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohort.id"))  # null = every cohort
    feedback_id = db.Column(db.Integer, db.ForeignKey("match_feedback.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("mentee_id", "mentor_id", "cohort_id"),)


# --- resources ---------------------------------------------------------------

class Resource(db.Model):
    """School resources listed on the mentee Resources tab."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    url = db.Column(db.String(500))
    category = db.Column(db.String(60), nullable=False)
    student_group = db.Column(db.String(120))  # shown first to mentees in this group
    sort = db.Column(db.Integer, default=0, server_default="0", nullable=False)
    is_active = db.Column(db.Boolean, default=True, server_default=db.true(), nullable=False)

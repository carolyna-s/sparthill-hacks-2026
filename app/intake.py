"""Intake: profiles, applications, and digital agreements."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .auth import role_required
from .matching import HARD_FILTER_DEFAULTS
from .extensions import db
from .models import Agreement, AgreementSignature, Application, Cohort, Profile, utcnow
from .program import unsigned_agreements
from .taxonomy import DAYS, INDUSTRIES, PERIODS, TAXONOMY

bp = Blueprint("intake", __name__)

# Application questions per role: (key, label). Answers are stored as JSON, so editing this
# list needs no migration.
QUESTIONS = {
    "mentee": [
        ("why", "Why do you want a mentor right now?"),
        ("success", "What would make this program a success for you?"),
        ("commitment", "How many hours per month can you commit?"),
    ],
    "mentor": [
        ("experience", "Describe your career path and experience."),
        ("why", "Why do you want to mentor?"),
        ("commitment", "How many hours per month can you commit?"),
    ],
}


# Hard filters: matching can't place someone without these, so they're required. Languages is
# a hard filter too, but optional: blank means English (matching.HARD_FILTER_DEFAULTS).
REQUIRED = {"availability": "at least one time you're available"}


def missing_profile_fields(p: Profile) -> list[str]:
    return [label for dim, label in REQUIRED.items() if not getattr(p, dim)]


def canonical_industry(typed: str) -> str:
    """A suggestion's own spelling if the user typed one (any case), else what they typed."""
    typed = " ".join(typed.split())[:120]
    return next((i for i in INDUSTRIES if i.lower() == typed.lower()), typed)


@bp.route("/profile", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def profile():
    p = current_user.profile
    if request.method == "POST":
        p.headline = request.form.get("headline", "").strip()
        p.bio = request.form.get("bio", "").strip()
        p.organization = request.form.get("organization", "").strip()
        p.industry = canonical_industry(request.form.get("industry", ""))
        for field in ("interests", "goals_other", "looking_for"):
            setattr(p, field, request.form.get(field, "").strip())
        for dim, allowed in TAXONOMY.items():
            setattr(p, dim, [t for t in request.form.getlist(dim) if t in allowed])
        p.languages = p.languages or HARD_FILTER_DEFAULTS["languages"]
        if current_user.role == "mentor":
            p.capacity = max(1, min(5, int(request.form.get("capacity") or 1)))
        else:
            p.prefers_alumni = bool(request.form.get("prefers_alumni"))
        db.session.commit()
        missing = missing_profile_fields(p)
        if missing:
            flash("Saved, but matching needs " + " and ".join(missing) + ".", "error")
            return redirect(url_for("intake.profile"))
        flash("Profile saved.", "ok")
        return redirect(url_for("intake.apply"))
    return render_template("intake/profile.html", p=p, days=DAYS, periods=PERIODS, industries=INDUSTRIES)


@bp.route("/apply", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def apply():
    app_row = current_user.application
    if app_row is None:
        cohort = db.session.query(Cohort).filter_by(is_active=True).order_by(Cohort.id.desc()).first()
        app_row = Application(user_id=current_user.id, cohort_id=cohort.id if cohort else None,
                              status="draft", answers={})
        db.session.add(app_row)
    questions = QUESTIONS[current_user.role]
    if request.method == "POST":
        if app_row.status != "draft":
            abort(409)
        app_row.answers = {k: request.form.get(k, "").strip() for k, _ in questions}
        if request.form.get("action") == "submit":
            if not all(app_row.answers.values()):
                flash("Answer every question before submitting.", "error")
            elif missing_profile_fields(current_user.profile):
                flash("Finish your profile before submitting: add "
                      + " and ".join(missing_profile_fields(current_user.profile)) + ".", "error")
            elif unsigned_agreements(current_user):
                flash("Sign the program agreements before submitting.", "error")
            else:
                app_row.status = "submitted"
                app_row.submitted_at = utcnow()
                flash("Application submitted. Staff will review it soon.", "ok")
        db.session.commit()
        return redirect(url_for("intake.apply"))
    db.session.commit()
    return render_template("intake/apply.html", application=app_row, questions=questions,
                           unsigned=unsigned_agreements(current_user))


@bp.get("/agreements")
@role_required("mentee", "mentor")
def agreements():
    rows = (db.session.query(Agreement)
            .filter(Agreement.is_active, Agreement.audience.in_(("all", current_user.role))).all())
    signed = {s.agreement_id: s for s in db.session.query(AgreementSignature).filter_by(user_id=current_user.id)}
    return render_template("intake/agreements.html", agreements=rows, signed=signed)


@bp.post("/agreements/<int:agreement_id>/sign")
@role_required("mentee", "mentor")
def sign(agreement_id: int):
    agreement = db.get_or_404(Agreement, agreement_id)
    typed = request.form.get("typed_name", "").strip()
    if typed.lower() != current_user.name.lower():
        flash("Type your full name exactly as on your account to sign.", "error")
    elif not db.session.query(AgreementSignature).filter_by(agreement_id=agreement.id,
                                                           user_id=current_user.id).first():
        db.session.add(AgreementSignature(agreement_id=agreement.id, user_id=current_user.id,
                                          typed_name=typed, ip_address=request.remote_addr))
        db.session.commit()
        flash(f"Signed “{agreement.title}”.", "ok")
    return redirect(url_for("intake.agreements"))

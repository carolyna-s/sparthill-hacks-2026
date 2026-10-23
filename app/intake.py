"""Intake: profiles, applications, and digital agreements."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .auth import role_required
from .extensions import db
from .models import Agreement, AgreementSignature, Application, Cohort, utcnow
from .program import unsigned_agreements
from .taxonomy import TAXONOMY

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


@bp.route("/profile", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def profile():
    p = current_user.profile
    if request.method == "POST":
        p.headline = request.form.get("headline", "").strip()
        p.bio = request.form.get("bio", "").strip()
        p.organization = request.form.get("organization", "").strip()
        for dim, allowed in TAXONOMY.items():
            setattr(p, dim, [t for t in request.form.getlist(dim) if t in allowed])
        if current_user.role == "mentor":
            p.capacity = max(1, min(5, int(request.form.get("capacity") or 1)))
        db.session.commit()
        flash("Profile saved.", "ok")
        return redirect(url_for("intake.apply"))
    return render_template("intake/profile.html", p=p)


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

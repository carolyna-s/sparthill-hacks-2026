"""Intake: profiles, applications, and digital agreements."""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from . import embeddings, linkedin, storage
from .auth import role_required
from .extensions import db
from .models import Agreement, AgreementSignature, Application, Cohort, User, utcnow
from .program import unsigned_agreements
from .taxonomy import DAYS, INDUSTRIES, PERIODS, TAXONOMY

bp = Blueprint("intake", __name__)


@bp.before_app_request
def require_profile_setup():
    """Keep first-time mentor and mentee accounts on their current onboarding step."""
    if not current_user.is_authenticated or current_user.role not in ("mentee", "mentor"):
        return None
    if profile_setup_complete(current_user):
        session.pop(_onboarding_session_key(current_user), None)
        return None
    if request.endpoint in {"static", "auth.logout", "intake.profile", "intake.profile_step",
                            "intake.account_profile"}:
        return None
    key = _onboarding_session_key(current_user)
    page = {
        "main.landing": "Home",
        "main.dashboard": "Dashboard",
        "intake.profile": "Profile",
        "intake.apply": "Application",
        "intake.agreements": "Agreements",
        "program.inbox": "Messages",
        "program.messages": "Messages",
        "program.modules": "Modules",
    }.get(request.endpoint, "this page")
    flash(f"Please complete onboarding to access {page}", "error")
    step = session.get(key)
    if not isinstance(step, int) or not 1 <= step <= len(STEPS):
        step = _resume_profile_step(current_user)
        session[key] = step
    return redirect(url_for("intake.profile_step", step=step))


# Application questions per role: (key, label). Answers are stored as JSON, so editing this
# list needs no migration.
Personality_Questions_Data = {
    "mentee": [
        ("mentorship_style", "What communication or mentorship style helps you learn most effectively?"),
        ("career_advice", "What type of advice would you like to receive as you begin or develop your career?"),
    ],
    "mentor": [
        ("mentorship_style", "What type of mentor do you see yourself being?"),
        ("career_advice", "What type of advice would you give someone beginning their career in your field?"),
    ],
}

# Profile prompts: the answers are stored on Profile, separately from application answers.
Industry_Relevant_Prompt_Data = {
    "mentee": {
        "interests": "What subjects are you interested in learning more about?",
    },
    "mentor": {
        "looking_for": "Relating to your industry experience, what do you bring to the table?",
    },
}


# The sign-up form, one page per step. Steps 1-2 (contact info and the hard filters matching
# can't do without) are required; 3-4 open once they're done and can be left blank.
STEPS = ("About you", "Availability & language", "Preferences", "In your own words")

# (step, check, what to ask for when it's missing)
REQUIRED = [
    (1, lambda u: u.name, "your name"),
    (1, lambda u: u.email, "your email"),
    (1, lambda u: u.profile.school, "your school"),
    (2, lambda u: u.profile.availability, "at least one time you're available"),
    (2, lambda u: u.profile.languages, "at least one language"),
]

# Tag pickers on each step.
STEP_TAGS = {2: ("availability", "languages"), 3: ("development_areas", "goals", "education_paths")}


def missing_fields(user: User, step: int | None = None) -> list[str]:
    return [label for s, ok, label in REQUIRED if step in (None, s) and not ok(user)]


def signup_next_step(user: User) -> str | None:
    """URL of the first unfinished sign-up step (profile, agreements, submit), or None when done."""
    if missing_fields(user):
        return url_for("intake.profile")
    if unsigned_agreements(user):
        return url_for("intake.agreements")
    if user.application is None or user.application.status == "draft":
        return url_for("intake.apply")
    return None


def missing_setup_answers(user: User) -> list[str]:
    """Return required free-response prompts left blank during account setup."""
    profile = user.profile
    prompts = Industry_Relevant_Prompt_Data[user.role]
    missing = [
        label for field, label in prompts.items()
        if not (getattr(profile, field) or "").strip()
    ]
    application = user.application
    if application is None:
        return missing + [label for _, label in Personality_Questions_Data[user.role]]
    if application.status != "draft":
        return []
    answers = application.answers or {}
    missing.extend(
        label for key, label in Personality_Questions_Data[user.role]
        if not (answers.get(key) or "").strip()
    )
    return missing


def profile_setup_complete(user: User) -> bool:
    """Whether this account has supplied the required profile and application answers."""
    if user.role not in ("mentee", "mentor") or user.profile is None:
        return True
    if user.application is not None and user.application.status != "draft":
        return True
    return not missing_fields(user) and not missing_setup_answers(user)


def _onboarding_session_key(user: User) -> str:
    return f"onboarding_step_{user.id}"


def _resume_profile_step(user: User) -> int:
    unfinished = [step for step, check, _ in REQUIRED if not check(user)]
    return min(unfinished) if unfinished else 4


def canonical_industry(typed: str) -> str:
    """A suggestion's own spelling if the user typed one (any case), else what they typed."""
    typed = " ".join(typed.split())[:120]
    return next((i for i in INDUSTRIES if i.lower() == typed.lower()), typed)


def _application(user: User) -> Application:
    if user.application is None:
        cohort = db.session.query(Cohort).filter_by(is_active=True).order_by(Cohort.id.desc()).first()
        user.application = Application(cohort_id=cohort.id if cohort else None, status="draft", answers={})
    return user.application


@bp.get("/profile")
@role_required("mentee", "mentor")
def profile():
    """Resume the same onboarding step, or begin at the first required step."""
    key = _onboarding_session_key(current_user)
    step = session.get(key)
    if not isinstance(step, int) or not 1 <= step <= len(STEPS):
        step = 1 if profile_setup_complete(current_user) else _resume_profile_step(current_user)
    session[key] = step
    return redirect(url_for("intake.profile_step", step=step))


@bp.route("/account", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def account_profile():
    p = current_user.profile
    if p is None:
        abort(409)

    profile_values = {
        "organization": p.organization or "",
        "headline": p.headline or "",
        "bio": p.bio or "",
        "linkedin_url": p.linkedin_url or "",
    }
    profile_error = None
    confirm_profile = False
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            company = request.form.get("organization", "").strip()
            headline = request.form.get("headline", "").strip()
            bio = request.form.get("bio", "").strip()
            linkedin_url = request.form.get("linkedin_url", "").strip()
            profile_values = {
                "organization": company,
                "headline": headline,
                "bio": bio,
                "linkedin_url": linkedin_url,
            }
            confirm_profile = True
            try:
                parsed_url = urlsplit(linkedin_url) if linkedin_url else None
            except ValueError:
                parsed_url = None
            if not current_user.check_password(request.form.get("current_password", "")):
                profile_error = "That password is incorrect. Verify your password and try again."
            elif len(company) > 200 or len(headline) > 200 or len(linkedin_url) > 300:
                profile_error = "Company, current role, or LinkedIn URL is too long."
            elif linkedin_url and (parsed_url is None or parsed_url.scheme not in {"http", "https"}
                                   or not parsed_url.netloc):
                profile_error = "Enter a valid LinkedIn URL beginning with http:// or https://."
            else:
                p.organization = company
                p.headline = headline
                p.bio = bio
                p.linkedin_url = linkedin_url or None
                db.session.commit()
                flash("Profile changes saved.", "ok")
                return redirect(url_for("intake.account_profile"))
        elif action == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if not current_user.check_password(current_password):
                flash("Your current password is incorrect.", "error")
            elif len(new_password) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new_password != confirm_password:
                flash("New password and confirmation do not match.", "error")
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash("Password changed successfully.", "ok")
                return redirect(url_for("intake.account_profile"))
        else:
            abort(400)

    return render_template("account/profile.html", profile=p, profile_values=profile_values,
                           profile_error=profile_error, confirm_profile=confirm_profile)


@bp.route("/profile/<int:step>", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def profile_step(step: int):
    if not 1 <= step <= len(STEPS):
        abort(404)
    if step > 2 and missing_fields(current_user):
        flash("Finish the required steps first: add " + " and ".join(missing_fields(current_user)) + ".", "error")
        return redirect(url_for("intake.profile"))
    session[_onboarding_session_key(current_user)] = step
    if request.method == "GET":
        return _render_step(step)

    ok = SAVE[step](current_user)
    if step in (3, 4):  # the steps with text boxes
        embeddings.refresh(current_user.profile)
    db.session.commit()
    if request.form.get("nav") == "back":
        previous_step = step - 1
        session[_onboarding_session_key(current_user)] = previous_step
        return redirect(url_for("intake.profile_step", step=previous_step))
    missing = missing_fields(current_user, step)
    if missing:
        flash("To continue, add " + " and ".join(missing) + ".", "error")
    if missing or not ok:
        return redirect(url_for("intake.profile_step", step=step))
    if step == len(STEPS):
        session.pop(_onboarding_session_key(current_user), None)
        return redirect(url_for("intake.apply"))
    next_step = step + 1
    session[_onboarding_session_key(current_user)] = next_step
    return redirect(url_for("intake.profile_step", step=next_step))


def _save_about(user: User) -> bool:
    p, form, ok = user.profile, request.form, True
    user.name = form.get("name", "").strip()[:120] or user.name
    email = form.get("email", "").strip().lower()
    if email and email != user.email:
        if "@" not in email:
            flash("That email doesn't look right.", "error")
            ok = False
        elif db.session.query(User).filter_by(email=email).first():
            flash("Another account already uses that email.", "error")
            ok = False
        else:
            user.email = email
    p.school = form.get("school", "").strip()[:200] or None
    for f in ("headline", "organization"):
        setattr(p, f, form.get(f, "").strip()[:200])
    p.bio = form.get("bio", "").strip()
    p.linkedin_url = form.get("linkedin_url", "").strip()[:300] or None
    file = request.files.get("linkedin_pdf")
    if file and file.filename:
        ok = _import_linkedin(user, file) and ok
    return ok


def _import_linkedin(user: User, file) -> bool:
    """Parse a LinkedIn PDF into suggestions for steps 2-3. Nothing on the form changes yet."""
    data = file.read()
    if not data.startswith(b"%PDF"):
        flash("That file isn't a PDF. On LinkedIn use More → Save to PDF, then upload it here.", "error")
        return False
    file.stream.seek(0)
    p = user.profile
    p.resume_key = storage.save(file, f"linkedin/{user.id}")
    p.resume_file_name = file.filename
    parsed = linkedin.parse(data, user.role)
    if parsed.get("industry"):
        parsed["industry"] = canonical_industry(parsed["industry"])
    p.linkedin_data = parsed
    n = sum(len(v) for v in parsed["tags"].values()) + bool(parsed.get("industry"))
    flash(f"Imported your LinkedIn profile: {n} suggestions are highlighted in the next steps.", "ok")
    return True


def _save_tags(user: User, step: int) -> None:
    p = user.profile
    for dim in STEP_TAGS[step]:
        setattr(p, dim, [t for t in request.form.getlist(dim) if t in TAXONOMY[dim]])
    if p.linkedin_data:  # suggestions on this step have been seen; don't re-add ones they removed
        p.linkedin_data = {**p.linkedin_data, "reviewed": sorted({*p.linkedin_data.get("reviewed", []), step})}


def _save_availability(user: User) -> bool:
    _save_tags(user, 2)
    if user.role == "mentor":
        user.profile.capacity = max(1, min(5, int(request.form.get("capacity") or 1)))
    return True


def _save_preferences(user: User) -> bool:
    p = user.profile
    _save_tags(user, 3)
    p.industry = canonical_industry(request.form.get("industry", ""))
    p.goals_other = request.form.get("goals_other", "").strip()
    if user.role == "mentee":
        p.prefers_alumni = bool(request.form.get("prefers_alumni"))
    return True


def _save_questions(user: User) -> bool:
    for f in ("interests", "looking_for"):
        setattr(user.profile, f, request.form.get(f, "").strip())
    app_row = _application(user)
    if app_row.status == "draft":
        app_row.answers = {k: request.form.get(k, "").strip()
                           for k, _ in Personality_Questions_Data[user.role]}
    missing = missing_setup_answers(user)
    if missing:
        flash("Answer each question before continuing: " + " ".join(missing), "error")
        return False
    return True


SAVE = {1: _save_about, 2: _save_availability, 3: _save_preferences, 4: _save_questions}


def _render_step(step: int):
    p = current_user.profile
    data = p.linkedin_data or {}
    parsed = {} if step in data.get("reviewed", []) else data  # LinkedIn suggestions, pre-selected
    suggested_tags = parsed.get("tags", {})
    sel = {dim: list(dict.fromkeys(getattr(p, dim) + suggested_tags.get(dim, []))) for dim in TAXONOMY}
    sel["languages"] = sel["languages"] or ["English"]  # the usual answer; one click to change
    suggested = {dim: set(v) - set(getattr(p, dim)) for dim, v in suggested_tags.items()}
    suggested["industry"] = bool(parsed.get("industry")) and not p.industry
    return render_template("intake/profile.html", p=p, step=step, steps=STEPS,
                           done={s: not missing_fields(current_user, s) for s in (1, 2)},
                           locked=bool(missing_fields(current_user)),
                           days=DAYS, periods=PERIODS, industries=INDUSTRIES, sel=sel,
                           industry=p.industry or parsed.get("industry", ""), suggested=suggested,
                           Personality_Questions_Data=Personality_Questions_Data[current_user.role],
                           Industry_Relevant_Prompt_Data=Industry_Relevant_Prompt_Data[current_user.role],
                           application=current_user.application)


@bp.route("/apply", methods=["GET", "POST"])
@role_required("mentee", "mentor")
def apply():
    """Review the answers from the sign-up form and submit them."""
    app_row = _application(current_user)
    if request.method == "POST":
        if app_row.status != "draft":
            abort(409)
        missing = missing_fields(current_user)
        if missing:
            flash("Finish your profile before submitting: add " + " and ".join(missing) + ".", "error")
        elif unsigned_agreements(current_user):
            flash("Sign the program agreements before submitting.", "error")
        else:
            app_row.status = "submitted"
            app_row.submitted_at = utcnow()
            flash("Application submitted. Staff will review it soon.", "ok")
            db.session.commit()
            return redirect(url_for("main.dashboard"))
        db.session.commit()
        return redirect(url_for("intake.apply"))
    db.session.commit()
    return render_template("intake/apply.html", application=app_row,
                           Personality_Questions_Data=Personality_Questions_Data[current_user.role],
                           missing=missing_fields(current_user), unsigned=unsigned_agreements(current_user))


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
        if not unsigned_agreements(current_user):
            return redirect(url_for("intake.apply"))
    return redirect(url_for("intake.agreements"))

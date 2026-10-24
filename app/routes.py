from __future__ import annotations

import calendar
import hmac
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import program
from .extensions import csrf, db
from .intake import Industry_Relevant_Prompt_Data, Personality_Questions_Data, missing_fields, signup_next_step
from .models import Event, Match, utcnow
from .taxonomy import DAYS, PERIODS, TAXONOMY

bp = Blueprint("main", __name__)


@bp.get("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    if current_user.is_staff:
        return redirect(url_for("staff.overview"))
    next_step = signup_next_step(current_user)
    if next_step:
        flash("Finish signing up to open your dashboard.", "error")
        return redirect(next_step)
    matches = (db.session.query(Match)
               .filter(Match.status == "approved",
                       (Match.mentee_id == current_user.id) | (Match.mentor_id == current_user.id))
               .all())
    return render_template("dashboard.html", application=current_user.application, matches=matches,
                           upcoming=program.upcoming_events(), todo=program.todo_for(current_user),
                           Personality_Questions_Data=Personality_Questions_Data,
                           cal=_month_calendar())


@bp.route("/dashboard/application", methods=["GET", "POST"])
@login_required
def update_application():
    if current_user.role not in ("mentee", "mentor"):
        abort(403)
    application = current_user.application
    if application is None or application.status == "draft":
        abort(409)

    if request.method == "GET":
        return render_template("application.html", application=application,
                               Personality_Questions_Data=Personality_Questions_Data,
                               Industry_Relevant_Prompt_Data=Industry_Relevant_Prompt_Data,
                               taxonomy=TAXONOMY, DAYS=DAYS, PERIODS=PERIODS)

    profile = current_user.profile
    profile.organization = request.form.get("organization", "").strip()[:200]
    profile.headline = request.form.get("headline", "").strip()[:200]
    profile.bio = request.form.get("bio", "").strip()
    profile.linkedin_url = request.form.get("linkedin_url", "").strip()[:300] or None
    profile.availability = [value for value in request.form.getlist("availability")
                            if value in TAXONOMY["availability"]]
    profile.languages = [value for value in request.form.getlist("languages")
                         if value in TAXONOMY["languages"]]
    profile.industry = request.form.get("industry", "").strip()[:120] or None
    profile.development_areas = [value for value in request.form.getlist("development_areas")
                                 if value in TAXONOMY["development_areas"]]
    profile.goals = [value for value in request.form.getlist("goals")
                     if value in TAXONOMY["goals"]]
    profile.goals_other = request.form.get("goals_other", "").strip()
    profile.education_paths = [value for value in request.form.getlist("education_paths")
                               if value in TAXONOMY["education_paths"]]
    profile.prefers_alumni = current_user.role == "mentee" and bool(request.form.get("prefers_alumni"))
    if current_user.role == "mentor":
        try:
            profile.capacity = max(1, min(5, int(request.form.get("capacity", "1"))))
        except ValueError:
            profile.capacity = 1
    profile.interests = request.form.get("interests", "").strip()
    profile.looking_for = request.form.get("looking_for", "").strip()

    answers = {key: request.form.get(key, "").strip()
               for key, _ in Personality_Questions_Data[current_user.role]}
    application.answers = {**(application.answers or {}), **answers}

    errors = []
    if missing_fields(current_user):
        errors.append("Complete the required school, availability, and language fields.")
    required_text = [
        label for key, label in Industry_Relevant_Prompt_Data[current_user.role].items()
        if not (getattr(profile, key) or "").strip()
    ]
    required_text.extend(label for key, label in Personality_Questions_Data[current_user.role]
                         if not answers[key])
    if required_text:
        errors.append("Answer each required question: " + " ".join(required_text))
    if profile.linkedin_url:
        try:
            parsed_linkedin = urlsplit(profile.linkedin_url)
        except ValueError:
            parsed_linkedin = None
        if (parsed_linkedin is None or parsed_linkedin.scheme not in {"http", "https"}
                or not parsed_linkedin.netloc):
            errors.append("Enter a valid LinkedIn URL beginning with http:// or https://.")
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("application.html", application=application,
                               Personality_Questions_Data=Personality_Questions_Data,
                               Industry_Relevant_Prompt_Data=Industry_Relevant_Prompt_Data,
                               taxonomy=TAXONOMY, DAYS=DAYS, PERIODS=PERIODS, editing=True)

    db.session.commit()
    flash("Application changes saved.", "ok")
    return redirect(url_for("main.update_application"))


def _month_calendar() -> dict:
    """This month as weeks of day numbers (0 = padding), with the events falling on each day."""
    today = utcnow().date()
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    by_day: dict[int, list] = {}
    for e in db.session.query(Event).filter(Event.starts_at >= start, Event.starts_at < end).order_by(Event.starts_at):
        by_day.setdefault(e.starts_at.day, []).append(e)
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(today.year, today.month)
    return {"title": today.strftime("%B %Y"), "today": today.day, "weeks": weeks, "events": by_day}


@bp.get("/healthz")
def healthz():
    db.session.execute(db.text("SELECT 1"))
    return {"ok": True}


@bp.post("/internal/cron/reminders")
@csrf.exempt
def cron_reminders():
    """Called by EventBridge Scheduler (or any cron) with `X-Cron-Secret`."""
    secret = current_app.config["CRON_SECRET"]
    if not secret or not hmac.compare_digest(request.headers.get("X-Cron-Secret", ""), secret):
        abort(403)
    from .reminders import send_due_reminders

    return {"sent": send_due_reminders()}

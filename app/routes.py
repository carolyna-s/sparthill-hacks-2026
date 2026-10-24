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
from .models import Event, Match, Meeting, Submission, utcnow
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
    if current_user.is_backend:
        return redirect(url_for("admin.dashboard"))
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
    meetings = program.meetings_for(current_user)
    upcoming = sorted([("meeting", mt.starts_at, mt) for mt in meetings if mt.starts_at >= utcnow() - timedelta(hours=1)]
                      + [("module", e.starts_at, e) for e in program.upcoming_modules()],
                      key=lambda row: row[1])[:5]
    return render_template("dashboard.html", application=current_user.application, matches=matches,
                           upcoming=upcoming, todo=program.todo_for(current_user),
                           Personality_Questions_Data=Personality_Questions_Data,
                           cal=_month_calendar(meetings))


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


def _month_calendar(meetings: list[Meeting]) -> dict:
    """This month as weeks of day numbers (0 = padding), with what falls on each day: module sessions,
    pre-/post-work due dates (mentees only), and the user's meetings. Each item is (kind, label, url)."""
    today = utcnow().date()
    start = today.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    dated: list[tuple] = []
    for e in db.session.query(Event).order_by(Event.starts_at):
        url = url_for("program.module", event_id=e.id)
        dated.append((e.starts_at, "module", e.title, url))
        if current_user.role == "mentee":
            for kind in Submission.KINDS:
                due = getattr(e, f"{kind}_due")
                if getattr(e, f"{kind}_prompt") and due:
                    dated.append((due, "due", f"{kind.replace('work', '-work').capitalize()} due: {e.title}", url))
    for mt in meetings:
        other = mt.match.other(current_user)
        dated.append((mt.starts_at, "meeting", f"Meeting with {other.name} at {mt.starts_at:%I:%M %p}",
                      url_for("program.messages", match_id=mt.match_id)))
    by_day: dict[int, list] = {}
    for when, kind, label, url in sorted(dated, key=lambda row: row[0]):
        if start <= when.date() < end:
            by_day.setdefault(when.day, []).append((kind, label, url))
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(today.year, today.month)
    return {"title": today.strftime("%B %Y"), "today": today.day, "weeks": weeks, "days": by_day}


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

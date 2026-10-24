"""Email + password accounts with three roles: mentee, mentor, staff.

Staff accounts can't self-register; a backend admin creates them (app/admin.py), or use
`flask seed`. Deactivated accounts can't log in. Swap in Amazon Cognito later by replacing this blueprint; the rest of the app
only relies on Flask-Login's `current_user` and `role_required`.
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .models import Profile, User, utcnow

bp = Blueprint("auth", __name__)


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        role = request.form.get("role")
        if role not in ("mentee", "mentor"):
            abort(400)
        if len(request.form["password"]) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif not request.form.get("school", "").strip():
            flash("Enter your school.", "error")
        elif db.session.query(User).filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(email=email, name=request.form["name"].strip(), role=role)
            user.set_password(request.form["password"])
            user.profile = Profile(school=request.form.get("school", "").strip())
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("intake.profile"))
    return render_template("auth/register.html", role=request.args.get("role", "mentee"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        user = db.session.query(User).filter_by(email=request.form["email"].strip().lower()).first()
        if user and user.check_password(request.form["password"]) and not user.is_active:
            flash("This account has been disabled. Contact the program administrator.", "error")
            return render_template("auth/login.html")
        if user and user.check_password(request.form["password"]):
            login_user(user, remember=True)
            user.last_login_at = utcnow()
            db.session.commit()
            if user.must_reset_password:
                return redirect(url_for("auth.required_password"))
            if user.role in ("mentee", "mentor"):
                from .intake import profile_setup_complete

                if not profile_setup_complete(user):
                    return redirect(url_for("intake.profile"))
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash("Wrong email or password.", "error")
    return render_template("auth/login.html")


@bp.route("/password-required", methods=["GET", "POST"])
@login_required
def required_password():
    if not current_user.must_reset_password:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new_password != request.form.get("confirm_password"):
            flash("New password and confirmation do not match.", "error")
        else:
            current_user.set_password(new_password)
            current_user.must_reset_password = False
            db.session.commit()
            flash("Your password has been updated.", "ok")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/password_required.html")


def change_password(user: User, form) -> str | None:
    """Apply a change-password form (current, new, confirm). Returns the error, if any."""
    if not user.check_password(form.get("current_password", "")):
        return "Your current password is incorrect."
    if len(form.get("new_password", "")) < 8:
        return "New password must be at least 8 characters."
    if form.get("new_password") != form.get("confirm_password"):
        return "New password and confirmation do not match."
    user.set_password(form["new_password"])
    db.session.commit()
    return None


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.landing"))

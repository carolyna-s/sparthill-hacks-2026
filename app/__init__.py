import logging

import click
from flask import Flask

from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(overrides: dict | None = None) -> Flask:
    logging.basicConfig(level=logging.INFO)
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  registers tables with SQLAlchemy
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .intake import bp as intake_bp
    from .program import bp as program_bp
    from .routes import bp as main_bp
    from .staff import bp as staff_bp

    for bp in (main_bp, auth_bp, intake_bp, program_bp, staff_bp, admin_bp):
        app.register_blueprint(bp)

    from .taxonomy import TAXONOMY

    @app.context_processor
    def inject_taxonomy():
        return {"taxonomy": TAXONOMY}

    @app.before_request
    def touch_last_seen():
        """Record activity for "last seen" on message threads, writing at most once a minute."""
        from datetime import timedelta

        from flask_login import current_user

        from .models import utcnow

        if current_user.is_authenticated:
            now = utcnow()
            if current_user.last_seen_at is None or now - current_user.last_seen_at > timedelta(minutes=1):
                current_user.last_seen_at = now
                db.session.commit()

    @app.template_filter("ago")
    def ago(when):
        """'just now', '5 min ago', '3 hr ago', 'yesterday', or a date."""
        from .models import utcnow

        secs = (utcnow() - when).total_seconds()
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{int(secs // 60)} min ago"
        if secs < 86400:
            return f"{int(secs // 3600)} hr ago"
        if secs < 2 * 86400:
            return "yesterday"
        return when.strftime("%b %d")

    @app.cli.command("send-reminders")
    def send_reminders_cmd():
        """Email everyone with something due (run on a schedule)."""
        from .reminders import send_due_reminders

        click.echo(f"sent {send_due_reminders()} reminders")

    @app.cli.command("embed")
    def embed_cmd():
        """Embed free-text answers that are new or changed (needs OPENAI_API_KEY)."""
        from .embeddings import backfill

        if not app.config["OPENAI_API_KEY"]:
            raise click.ClickException("OPENAI_API_KEY isn't set, so there's nothing to embed with.")
        done, failed = backfill()
        click.echo(f"{done} profiles up to date" + (f", {failed} failed (see the log)" if failed else ""))

    @app.cli.command("seed")
    def seed_cmd():
        """Fill the database with demo users, a cohort, and a sample module."""
        from .seed import seed

        seed()
        click.echo("seeded")

    @app.cli.command("seed-pool")
    def seed_pool_cmd():
        """Add 3 accepted, unmatched mentors and 3 mentees to try out matching."""
        from .seed import seed_pool

        try:
            click.echo(f"added {seed_pool()} people to the matching pool")
        except RuntimeError as e:
            raise click.ClickException(str(e))

    return app

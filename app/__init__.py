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
    from .auth import bp as auth_bp
    from .intake import bp as intake_bp
    from .program import bp as program_bp
    from .routes import bp as main_bp
    from .staff import bp as staff_bp

    for bp in (main_bp, auth_bp, intake_bp, program_bp, staff_bp):
        app.register_blueprint(bp)

    from .taxonomy import TAXONOMY

    @app.context_processor
    def inject_taxonomy():
        return {"taxonomy": TAXONOMY}

    @app.cli.command("send-reminders")
    def send_reminders_cmd():
        """Email everyone with something due (run on a schedule)."""
        from .reminders import send_due_reminders

        click.echo(f"sent {send_due_reminders()} reminders")

    @app.cli.command("seed")
    def seed_cmd():
        """Fill the database with demo users, a cohort, and events."""
        from .seed import seed

        seed()
        click.echo("seeded")

    return app

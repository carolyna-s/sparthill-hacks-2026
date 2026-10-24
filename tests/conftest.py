import os
import tempfile

import pytest

# Tests use a throwaway SQLite file and upload dir, never .env's Supabase database or bucket.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="mp-test-"), "test.db")
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
os.environ["EMAIL_BACKEND"] = "console"
os.environ["ANTHROPIC_API_KEY"] = ""  # LinkedIn import uses the offline keyword pass
os.environ["OPENAI_API_KEY"] = ""  # no embedding calls; tests stub app.embeddings.embed

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.seed import PASSWORD, seed  # noqa: E402


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "CRON_SECRET": "test-secret",
                      "UPLOAD_DIR": tempfile.mkdtemp(prefix="mp-uploads-")})
    with app.app_context():
        db.drop_all()
        seed()
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email: str, password: str = PASSWORD):
    return client.post("/login", data={"email": email, "password": password})

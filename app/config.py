import os

from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    """Supabase Postgres (create_app refuses anything else outside tests)."""
    url = os.getenv("DATABASE_URL", "")
    # Supabase hands out postgres:// or postgresql:// URLs; SQLAlchemy would pick psycopg2 for
    # those, but we install psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-secret")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB uploads

    # Uploads go to a private Supabase Storage bucket (app/storage.py). The service-role key is
    # server-only; never send it to the browser.
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "uploads")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.getcwd(), "data", "uploads"))  # tests only

    EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "console")  # every email is also in EmailLog
    AWS_REGION = os.getenv("AWS_REGION", "us-west-2")  # for SES
    MAIL_FROM = os.getenv("MAIL_FROM", "mentorship@example.org")
    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

    CRON_SECRET = os.getenv("CRON_SECRET", "")

    # LinkedIn PDF import uses Claude when set, else a keyword pass (app/linkedin.py)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Embeddings of the free-text answers for matching (app/embeddings.py); off when blank
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    # Reminder windows
    DUE_SOON_HOURS = 48
    UNREAD_MESSAGE_HOURS = 24

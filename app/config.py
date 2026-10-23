import os

from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        os.makedirs("instance", exist_ok=True)
        return "sqlite:///" + os.path.join(os.getcwd(), "instance", "mentorship.db")
    # Supabase/RDS hand out postgres:// or postgresql:// URLs; SQLAlchemy would pick psycopg2
    # for those, but we install psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-secret")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB uploads

    S3_BUCKET = os.getenv("S3_BUCKET", "")
    AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.getcwd(), "data", "uploads"))

    EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "console")
    MAIL_FROM = os.getenv("MAIL_FROM", "mentorship@example.org")
    BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

    CRON_SECRET = os.getenv("CRON_SECRET", "")

    # Reminder windows
    DUE_SOON_HOURS = 48
    UNREAD_MESSAGE_HOURS = 24

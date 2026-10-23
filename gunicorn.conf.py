import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
# All state lives in the database, so workers can scale freely.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
timeout = 60
accesslog = "-"

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000
# Apply migrations, then serve. Safe to run on every boot.
CMD ["sh", "-c", "flask --app wsgi db upgrade && gunicorn -c gunicorn.conf.py wsgi:app"]

# Build from the repo root:  docker build -f backend/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scraper/ scraper/
COPY db/ db/

WORKDIR /app/backend
EXPOSE 8000
# Migrate, then serve. Migrations are idempotent so restarts are safe.
CMD ["sh", "-c", "python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

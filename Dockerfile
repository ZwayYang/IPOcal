FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static

# SQLite lives in container FS by default. For persistent storage on a platform,
# mount /app/data.sqlite3 or use a managed DB later.

EXPOSE 8000

# Many platforms (e.g. Render/Fly) set $PORT dynamically.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]


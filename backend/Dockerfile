FROM python:3.12-slim

WORKDIR /app

# postgresql-client: pg_dump/pg_restore for app/db/maintenance.py's ad hoc
# snapshot commands (docs/PRODUCTION.md). Debian's package tracks its own
# release, one version behind the postgres:16 servers used elsewhere in this
# project — fine for pg_dump's custom format across a one-version gap, and
# these commands are explicitly for ad hoc snapshots, not routine backup (the
# managed provider's own automated backups are, and don't have this concern).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 atom && useradd --uid 10001 --gid atom --no-create-home atom \
    && mkdir -p /home/atom && chown -R atom:atom /home/atom
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/home/atom

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .
RUN chown -R atom:atom /app

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

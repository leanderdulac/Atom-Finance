FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 atom && useradd --uid 10001 --gid atom --no-create-home atom \
    && mkdir -p /data /home/atom && chown -R atom:atom /data /home/atom
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/home/atom

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .
RUN chown -R atom:atom /app

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
WORKDIR /app
COPY quantmind ./quantmind
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY service.py .
RUN useradd --create-home researcher && mkdir /data && chown researcher /data
USER researcher
ENV QUANTMIND_DB_PATH=/data/research.db
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8010"]

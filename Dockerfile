FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/output /app/cache /app/logs /app/config

VOLUME ["/app/output", "/app/cache", "/app/logs", "/app/config"]

ENV PYTHONPATH=/app

CMD ["python", "-m", "src.main", "--config", "/app/config/config.yaml"]

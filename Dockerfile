FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tracker ./tracker

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_FILE=/data/state/seen_pools.json

# Default exposes both the metrics/healthz port (configurable via
# METRICS_PORT). The container itself does not require this — Compose
# wires it through.
EXPOSE 9100

CMD ["python", "-m", "tracker"]

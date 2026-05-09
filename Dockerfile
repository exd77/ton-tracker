FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY tracker.py ./tracker.py
COPY state ./state

ENV PYTHONUNBUFFERED=1
CMD ["python", "tracker.py"]

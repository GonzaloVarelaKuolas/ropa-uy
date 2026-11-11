# Debian slim + Python 3.12: the "OS + Python" layer
FROM python:3.12-slim

# No .pyc files; print logs immediately so `kubectl logs` shows them live
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is reused while only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Then the code
COPY scraper/ scraper/

# Never run as root (Kubernetes also enforces this, with the same UID)
RUN useradd --uid 10001 --create-home appuser
USER 10001

CMD ["python", "-m", "scraper", "run"]

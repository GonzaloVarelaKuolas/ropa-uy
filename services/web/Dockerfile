FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is reused while only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code, templates and static files (CSS, fonts)
COPY web/ web/

RUN useradd --uid 10001 --create-home appuser
USER 10001

EXPOSE 8000
# --proxy-headers: trust the forwarded scheme/host once an ingress sits in front
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

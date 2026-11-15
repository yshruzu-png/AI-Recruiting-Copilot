# AI Recruiting Copilot API + chat page, for Azure Container Apps.
# Build for Container Apps (linux/amd64), even on an Apple Silicon Mac:
#   docker build --platform linux/amd64 -t recruiting-copilot .
# or in the cloud, no local Docker needed:
#   az acr build -r <registry> -t recruiting-copilot:<tag> .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src AUDIT_LOG=/tmp/logs/audit.jsonl

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ src/
COPY web/ web/
# The synthetic candidate pool: extracted blind-able profiles, requirements and job definitions.
# (Fake people only. data/submissions/ holds approved drafts with names and is never copied.)
COPY data/extracted/ data/extracted/
COPY data/synthetic/ground_truth.json data/synthetic/ground_truth.json
COPY data/synthetic/resumes/ data/synthetic/resumes/

# Run as an unprivileged user; the app only needs to write its audit log under /tmp.
RUN useradd --create-home --uid 10001 app && mkdir -p /tmp/logs && chown app /tmp/logs
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

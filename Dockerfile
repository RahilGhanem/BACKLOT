# Cloud Run image for the BACKLOT FastAPI backend + web UI
# (backlot/api/app.py). Build/deploy with deploy/cloud_run/deploy.sh, or
# see docs/DEPLOYMENT.md for the equivalent gcloud commands.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backlot ./backlot
COPY data ./data

# Cloud Run injects PORT and requires the container to listen on it;
# backlot/config.py already prefers PORT over API_PORT for exactly this.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn backlot.api.app:app --host 0.0.0.0 --port ${PORT}"]

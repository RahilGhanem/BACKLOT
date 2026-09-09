# Container image for the BACKLOT API and web UI.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backlot ./backlot
COPY data ./data
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# The host injects PORT and requires the container to listen on it;
# config.py prefers PORT over API_PORT for exactly this.
ENV PORT=8080
EXPOSE 8080

CMD ["./docker-entrypoint.sh"]

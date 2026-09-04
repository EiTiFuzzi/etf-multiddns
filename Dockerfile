FROM python:3.12-slim

# Filled in by the release workflow at build time with the Git tag
# (--build-arg APP_VERSION=<tag>), so the Web UI can show the running
# version in the footer below. On a local "docker build ." without a
# build arg, it stays at the placeholder "dev".
ARG APP_VERSION=dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_PATH=/config/config.json \
    PORT=8080 \
    PORT_HTTPS=8443 \
    APP_VERSION=${APP_VERSION}

WORKDIR /srv

# tzdata: required so real IANA timezone names (Settings -> Timezone) can
# actually be resolved (zoneinfo/time.tzset()).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /config
VOLUME ["/config"]

# 8080 (HTTP) is always active; 8443 (HTTPS) only actually answers once
# HTTPS is turned on under Settings - it's exposed here regardless so the
# port mapping/documentation doesn't have to change when that's flipped on.
EXPOSE 8080 8443

# Deliberately checks HTTP, not HTTPS: HTTP stays available even with HTTPS
# enabled (see app/https_server.py), and checking it avoids the healthcheck
# having to deal with a self-signed certificate.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8080') + '/api/status', timeout=3)" || exit 1

# The optional HTTPS listener (port 8443, self-signed by default) isn't
# started by gunicorn itself - it's a thread spun up from within app/main.py
# (imported once here, on worker boot) so it can share the same in-memory
# DDNSService state as the plain HTTP server below. See app/https_server.py.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "app.main:app"]

FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HH_NOVNC_ENABLED=1 \
    HH_CHROMIUM_INSTALLED=1 \
    HH_STATE_DIR=/var/lib/job-search-hh/state \
    HH_PROFILE_DIR=/var/lib/job-search-hh/profile \
    HH_DISPLAY=:99 \
    HH_NOVNC_PORT=6080 \
    HH_VNC_PORT=5900

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium \
    && chmod +x /app/scripts/hh-browser-runtime.sh

# Chromium/Playwright/noVNC are installed in this image. Interactive HH login remains
# a separate operator action through loopback noVNC.
CMD ["/app/scripts/hh-browser-runtime.sh"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY src ./src

# The scaffold is a diagnostic CLI only. Chromium, Playwright and noVNC enter in
# their dedicated slice and must not be implied by this minimal image.
CMD ["python", "-m", "job_search_hh.cli", "capabilities"]


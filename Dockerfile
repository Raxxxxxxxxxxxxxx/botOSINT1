# Multi-stage build. Originally kept lean for Railway's free/trial ~512MB
# cap (Phase-2 decision) — that constraint is gone now that the bot is
# self-hosted, which is what makes installing a real browser below
# affordable at all.

FROM python:3.12-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

# Chromium for the Selenium-based Facebook adapter
# (scrapers/facebook_selenium_adapter.py) — replaces the Phase-2 "no
# headless browser" rule now that the bot isn't on Railway anymore.
# Selenium Manager auto-downloads a matching chromedriver at container
# startup; only the browser binary itself needs installing here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SELENIUM_CHROME_BINARY=/usr/bin/chromium

COPY . .
RUN mkdir -p /app/data /app/logs

CMD ["python", "main.py"]

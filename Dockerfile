# Multi-stage build to keep the final image small — Railway's free/trial
# tier caps RAM at ~512MB, so a lean runtime image matters (Phase-2 decision).

FROM python:3.12-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY . .
RUN mkdir -p /app/data /app/logs

# No headless browser, no local ML model — deliberate, per the Phase-2
# resource budget for Railway's free/trial tier.
CMD ["python", "main.py"]

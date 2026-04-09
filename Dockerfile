# syntax=docker/dockerfile:1.6
#
# 0pnMatrx gateway image.
#
# Multi-stage build:
#   1. ``builder`` installs Python dependencies into a virtualenv. Build
#      tools (gcc, etc.) live only in this stage so they don't bloat the
#      runtime image.
#   2. ``runtime`` copies the prebuilt venv plus application code, runs
#      as a non-root user, and exposes the gateway HTTP port.

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for native wheels (eth-hash, pynacl, etc.).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libssl-dev \
        libffi-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    OPNMATRX_HOME=/app

# Minimal runtime libs (sqlite3 is part of stdlib but the C library is needed
# at runtime; tini gives us a proper PID 1 for clean shutdown signals).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
        libffi8 \
        libsqlite3-0 \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --system --gid 1000 opnmatrx \
    && useradd --system --uid 1000 --gid opnmatrx --home /app --shell /sbin/nologin opnmatrx

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=opnmatrx:opnmatrx . /app

# Persistent state lives under /app/data — mount this as a volume.
RUN mkdir -p /app/data /app/data/backups \
    && chown -R opnmatrx:opnmatrx /app/data

USER opnmatrx
EXPOSE 18790

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:18790/health', timeout=3).status==200 else 1)" \
    || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "gateway.server"]

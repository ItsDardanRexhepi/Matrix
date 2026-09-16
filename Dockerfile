# syntax=docker/dockerfile:1.6
#
# 0pnMatrx gateway image.
#
# Multi-stage build:
#   1. ``builder`` installs Python dependencies into a virtualenv, from
#      hashed locks and wheels only.
#   2. ``runtime`` copies the prebuilt venv plus application code, runs
#      as a non-root user, and exposes the gateway HTTP port.
#
# Every input the builder takes is pinned to content, not to a name that can
# move. The base image is pinned by digest: `python:3.11-slim` alone is
# re-pointed on every Python and Debian patch release. That digest is the
# multi-arch index for python:3.11.16-slim-trixie as of 2026-09-12. pip and
# setuptools come from requirements-build.txt, and every runtime package from
# requirements.txt. Each is exact and --require-hashes, so a new version, or
# a new file uploaded for a pinned version, is refused. --only-binary=:all:
# means nothing is compiled, so no unpinned build backend (setuptools, a
# Rust or C toolchain) takes part in the build; the compiler packages this
# stage used to apt-get are gone with it. Still floating, and so NOT
# bit-for-bit reproducible: the runtime stage's apt-get packages below come
# from whatever the Debian mirror serves that day.
#
# To move the base image: resolve the new digest (for example
# `docker buildx imagetools inspect python:3.11-slim`), replace BOTH FROM
# lines, rebuild, and run the suite in the result.

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11.16-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements-build.txt requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --require-hashes -r requirements-build.txt \
    && /opt/venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
# Same digest as the builder: the venv's compiled wheels were chosen for it.
FROM python:3.11.16-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS runtime

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

# RUN-7: probes /ready, not /health. /health is liveness and answers 200 as long
# as the process is up — including when every model provider is unreachable — so
# an orchestrator using it as a routing signal sends traffic to an instance that
# cannot serve. Container health IS a routing signal, so it asks /ready.
# A 503 raises HTTPError here, and an unhandled exception exits 1, which is
# exactly the "unhealthy" the check wants — no wrapper needed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:18790/ready', timeout=3).status==200 else 1)" \
    || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "gateway.server"]

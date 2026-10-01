# SAGARAKSHAK MVP
# Standard library only, so the image is just Python + the app.
# python:3.12-slim is a multi-arch image (amd64, arm64, arm/v7, ppc64le, s390x, 386),
# so the same Dockerfile builds on x86 PCs, Apple Silicon, Raspberry Pi and cloud ARM.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Run as an unprivileged user
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --chown=app:app mvp/ /app/

# Signing key and catch reports are written here on first run
RUN mkdir -p /app/data && chown app:app /app/data
VOLUME ["/app/data"]

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

CMD ["python", "server.py"]

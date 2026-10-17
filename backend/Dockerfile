FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG CUSTOM_CA_CERT_B64=
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=

# Manim animates the working (app/manim_board.py): Cairo and Pango to draw,
# LaTeX and dvisvgm to set the maths. Without them the board draws it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        ca-certificates \
        build-essential pkg-config libcairo2-dev libpango1.0-dev \
        texlive-latex-base texlive-latex-extra texlive-fonts-recommended dvisvgm \
        && update-ca-certificates \
        && if [ -n "$CUSTOM_CA_CERT_B64" ]; then \
                 echo "$CUSTOM_CA_CERT_B64" | base64 -d > /usr/local/share/ca-certificates/custom-root-ca.crt && \
                 update-ca-certificates; \
             fi \
        && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi && \
    if [ -n "$PIP_EXTRA_INDEX_URL" ]; then pip config set global.extra-index-url "$PIP_EXTRA_INDEX_URL"; fi

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# A Chromium of our own, for when the stack's browser service is not there to
# connect to (see app/services/browser.py). Installed as root with its system
# libraries, readable by the app user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

COPY app /app/app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

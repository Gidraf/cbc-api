# The browser poster: a real browser on a virtual screen, shown in the
# console through noVNC, that publishes the platform's scheduled social posts
# from the sessions the owner logs into by hand.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

# Non-interactive, and downloads retried: a package cut short mid-download is
# fetched again instead of failing the build. tzdata is NOT installed or
# upgraded: the Playwright image already has it, and its 2026e upgrade fails
# to unpack in this image (dpkg error 1). The browser's time zone is set by
# the poster itself (Africa/Nairobi), so nothing here needs a newer one.
ENV DEBIAN_FRONTEND=noninteractive TZ=Africa/Nairobi
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries \
    && (apt-mark hold tzdata tzdata-legacy >/dev/null 2>&1 || true) \
    && apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc fluxbox novnc websockify fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# --ignore-installed: the base image's typing_extensions came from apt, and
# pip cannot uninstall what apt installed.
RUN pip install --no-cache-dir --ignore-installed -r requirements.txt

# Google Chrome where Google builds it (x86-64); the bundled Chromium elsewhere.
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then python -m playwright install --with-deps chrome || true; fi

COPY poster ./poster
COPY start.sh .

ENV DISPLAY=:99 \
    TZ=Africa/Nairobi \
    PROFILE_DIR=/data/profile \
    SHOTS_DIR=/data/shots \
    TMP_DIR=/data/tmp \
    PYTHONUNBUFFERED=1

EXPOSE 6080 6090
CMD ["bash", "start.sh"]

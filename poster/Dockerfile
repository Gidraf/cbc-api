# The browser poster: a real browser on a virtual screen, shown in the
# console through noVNC, that publishes the platform's scheduled social posts
# from the sessions the owner logs into by hand.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc fluxbox novnc websockify fonts-noto-color-emoji tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHANNEL_LIST=/config/recording-channels.txt \
    SETTINGS_FILE=/config/settings.json \
    BASE_DIR=/recordings \
    CHECK_INTERVAL=30 \
    VIDEO_CRF=23 \
    VIDEO_PRESET=veryfast \
    AUDIO_BITRATE=192k

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt yt-dlp

COPY auto-recorder.sh start.sh ./
COPY dashboard ./dashboard

RUN chmod +x /app/auto-recorder.sh /app/start.sh \
    && mkdir -p /config /recordings

EXPOSE 8090
VOLUME ["/config", "/recordings"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8090/status >/dev/null || exit 1

CMD ["/app/start.sh"]

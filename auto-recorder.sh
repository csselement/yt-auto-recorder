#!/bin/bash
set -u

CHANNELS_FILE="${CHANNEL_LIST:-/config/recording-channels.txt}"
BASE_DIR="${BASE_DIR:-/recordings}"
SETTINGS_FILE="${SETTINGS_FILE:-/config/settings.json}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"
VIDEO_CRF="${VIDEO_CRF:-23}"
VIDEO_PRESET="${VIDEO_PRESET:-veryfast}"
AUDIO_BITRATE="${AUDIO_BITRATE:-192k}"
YTDLP="${YTDLP:-$(command -v yt-dlp || true)}"

if [[ -z "$YTDLP" || ! -x "$YTDLP" ]]; then
    echo "ERROR: yt-dlp not found. Install yt-dlp or set YTDLP=/path/to/yt-dlp."
    exit 1
fi

mkdir -p "$(dirname "$CHANNELS_FILE")" "$BASE_DIR"
touch "$CHANNELS_FILE"
if [[ ! -f "$SETTINGS_FILE" ]]; then
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    printf '{"channels": {}}\n' > "$SETTINGS_FILE"
fi

slugify() {
    local url="$1"
    url="${url#https://}"
    url="${url#http://}"
    url="${url#www.}"
    echo "$url" | sed -E 's/[^A-Za-z0-9]+/_/g; s/^_+//; s/_+$//'
}

live_url() {
    local url="$1"
    url="${url%%\?*}"
    url="${url%/}"

    if [[ "$url" =~ youtube\.com/@[^/]+$ || "$url" =~ youtube\.com/(c|channel|user)/[^/]+$ ]]; then
        echo "$url/live"
    else
        echo "$url"
    fi
}

write_state() {
    local statefile="$1"
    local status="$2"
    local ts="$3"
    printf '{"status": "%s", "timestamp": "%s"}\n' "$status" "$ts" > "$statefile"
}

resolve_stream_url() {
    local url="$1"
    "$YTDLP" --no-warnings --no-playlist -g "$url" 2>/dev/null | head -n 1
}

channel_is_active() {
    local url="$1"
    [[ "$(jq -r --arg url "$url" '.channels[$url].active // .recording_active // true' "$SETTINGS_FILE" 2>/dev/null)" == "true" ]]
}

is_recording() {
    local lockfile="$1"
    if [[ ! -f "$lockfile" ]]; then
        return 1
    fi

    local pid
    pid="$(cat "$lockfile" 2>/dev/null || true)"
    if [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    rm -f "$lockfile"
    return 1
}

transcode_to_mp4() {
    local input="$1"
    local output="$2"
    local logfile="$3"

    ffmpeg -y \
        -loglevel warning \
        -i "$input" \
        -map 0:v:0 \
        -map 0:a? \
        -c:v libx264 \
        -preset "$VIDEO_PRESET" \
        -crf "$VIDEO_CRF" \
        -c:a libmp3lame \
        -b:a "$AUDIO_BITRATE" \
        -movflags +faststart \
        "$output" >> "$logfile" 2>&1
}

concat_transcode_to_mp4() {
    local listfile="$1"
    local output="$2"
    local logfile="$3"

    ffmpeg -y \
        -loglevel warning \
        -f concat \
        -safe 0 \
        -i "$listfile" \
        -map 0:v:0 \
        -map 0:a? \
        -c:v libx264 \
        -preset "$VIDEO_PRESET" \
        -crf "$VIDEO_CRF" \
        -c:a libmp3lame \
        -b:a "$AUDIO_BITRATE" \
        -movflags +faststart \
        "$output" >> "$logfile" 2>&1
}

finalize_mkvs() {
    local ch_dir="$1"
    local logfile="$2"
    local statefile="$3"
    local lockfile="$4"

    mapfile -t mkvs < <(find "$ch_dir" -maxdepth 1 -type f -name "*.mkv" | sort)
    if [[ "${#mkvs[@]}" -eq 0 ]]; then
        rm -f "$lockfile"
        return 0
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') --- Finalizing ${#mkvs[@]} MKV file(s) to H.264 MP4 with ${AUDIO_BITRATE} MP3 audio ---" | tee -a "$logfile"
    write_state "$statefile" "remuxing" "$(date '+%Y-%m-%d %H:%M:%S')"

    local output
    if [[ "${#mkvs[@]}" -eq 1 ]]; then
        output="${mkvs[0]%.mkv}.mp4"
        transcode_to_mp4 "${mkvs[0]}" "$output" "$logfile"
    else
        local first_base listfile escaped
        first_base="$(basename "${mkvs[0]}" .mkv)"
        output="$ch_dir/${first_base}_combined.mp4"
        listfile="$(mktemp "$ch_dir/.concat-XXXXXX.txt")"
        for mkv in "${mkvs[@]}"; do
            escaped="${mkv//\'/\'\\\'\'}"
            printf "file '%s'\n" "$escaped" >> "$listfile"
        done
        concat_transcode_to_mp4 "$listfile" "$output" "$logfile"
        rm -f "$listfile"
    fi

    if [[ -s "$output" ]]; then
        rm -f "${mkvs[@]}" "$lockfile"
        write_state "$statefile" "offline" "$(date '+%Y-%m-%d %H:%M:%S')"
        echo "$(date '+%Y-%m-%d %H:%M:%S') --- Finalize successful. MKV file(s) removed. Output: $output ---" | tee -a "$logfile"
        return 0
    fi

    write_state "$statefile" "error" "$(date '+%Y-%m-%d %H:%M:%S')"
    echo "$(date '+%Y-%m-%d %H:%M:%S') --- Finalize FAILED. MKV file(s) kept for safety. ---" | tee -a "$logfile"
    return 1
}

record_stream() {
    local url="$1"
    local ch_dir="$2"
    local logfile="$3"
    local statefile="$4"
    local lockfile="$5"
    trap 'rm -f "$lockfile"' EXIT

    log() {
        echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$logfile"
    }

    local timestamp out_mkv
    timestamp=$(date '+%Y-%m-%d_%H-%M-%S')
    out_mkv="$ch_dir/${timestamp}.mkv"

    log "--- LIVE detected. Attempting live-from-start MKV recording: $out_mkv ---"
    write_state "$statefile" "recording" "$timestamp"

    "$YTDLP" \
        --no-warnings \
        --no-playlist \
        --no-part \
        --live-from-start \
        --hls-use-mpegts \
        --merge-output-format mkv \
        -o "$out_mkv" \
        "$url" >> "$logfile" 2>&1

    if [[ ! -s "$out_mkv" ]]; then
        log "--- live-from-start did not produce a recording. Falling back to direct stream capture. ---"
        local stream_url
        stream_url=$(resolve_stream_url "$url")
        if [[ -z "$stream_url" ]]; then
            write_state "$statefile" "error" "$(date '+%Y-%m-%d %H:%M:%S')"
            log "WARNING: Unable to get stream URL for $url"
            return
        fi

        ffmpeg -y \
            -loglevel warning \
            -i "$stream_url" \
            -map 0 \
            -c copy \
            -f matroska \
            "$out_mkv" >> "$logfile" 2>&1
    fi

    log "--- Recording stopped. Finalizing MKV file(s). ---"
    finalize_mkvs "$ch_dir" "$logfile" "$statefile" "$lockfile"
}

check_and_record() {
    URL="$1"
    CHECK_URL=$(live_url "$URL")
    SAFE=$(slugify "$URL")

    CH_DIR="$BASE_DIR/${SAFE}"
    mkdir -p "$CH_DIR"

    LOGFILE="$CH_DIR/recorder.log"
    STATEFILE="$CH_DIR/state.json"
    LOCKFILE="$CH_DIR/recording.pid"

    log() {
        echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGFILE"
    }

    log "Checking $CHECK_URL"

    # Check if live. Some YouTube /live pages resolve a stream URL even when
    # metadata detection is flaky, so direct stream resolution is the fallback.
    IS_LIVE=$("$YTDLP" --quiet --no-warnings --skip-download --print "%(is_live)s" "$CHECK_URL" 2>/dev/null | head -n 1)

    if [[ "$IS_LIVE" != "True" ]]; then
        STREAM_PROBE=$(resolve_stream_url "$CHECK_URL")
        if [[ -n "$STREAM_PROBE" ]]; then
            log "Metadata did not report live (is_live=$IS_LIVE), but stream URL resolved. Recording anyway."
        else
            log "Not live yet (is_live=${IS_LIVE:-empty})."
        fi
    fi

    if [[ "$IS_LIVE" != "True" && -z "${STREAM_PROBE:-}" ]]; then
        if [[ -f "$STATEFILE" ]]; then
            PREV_STATUS=$(jq -r .status "$STATEFILE" 2>/dev/null)
            if [[ "$PREV_STATUS" == "recording" ]]; then
                write_state "$STATEFILE" "offline" "$(date '+%Y-%m-%d %H:%M:%S')"
                log "--- Stream ended (detected). Marked OFFLINE."
            fi
        else
            write_state "$STATEFILE" "monitoring" "Never"
        fi
        if ! is_recording "$LOCKFILE"; then
            finalize_mkvs "$CH_DIR" "$LOGFILE" "$STATEFILE" "$LOCKFILE"
        fi
        return
    fi

    if is_recording "$LOCKFILE"; then
        log "Already recording; skipping duplicate start."
        return
    fi

    if ! channel_is_active "$URL"; then
        write_state "$STATEFILE" "live_inactive" "Live, recording off"
        log "Channel recording is off; live stream detected but no new recording will start."
        return
    fi

    record_stream "$CHECK_URL" "$CH_DIR" "$LOGFILE" "$STATEFILE" "$LOCKFILE" &
    echo "$!" > "$LOCKFILE"
}

while true; do
    while IFS= read -r URL; do
        [[ -z "$URL" ]] && continue
        [[ "$URL" =~ ^# ]] && continue
        check_and_record "$URL"
    done < "$CHANNELS_FILE"

    sleep "$CHECK_INTERVAL"
done

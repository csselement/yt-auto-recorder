#!/bin/bash

CHANNEL_LIST="$HOME/recording-channels.txt"
BASE_DIR="/mnt/nas/recordings"

write_state() {
    local chdir="$1"
    local state="$2"
    echo "{\"status\": \"$state\", \"timestamp\": \"$(date)\"}" > "$chdir/state.json"
}

while true; do
    while IFS= read -r CHANNEL_URL; do
        [ -z "$CHANNEL_URL" ] && continue

        CHNAME=$(echo "$CHANNEL_URL" | sed 's#https://##; s#http://##; s#www\.##; s#[^a-zA-Z0-9]#_#g')
        OUTDIR="${BASE_DIR}/${CHNAME}"
        mkdir -p "$OUTDIR"
        LOGFILE="${OUTDIR}/recorder.log"

        write_state "$OUTDIR" "monitoring"
        echo "$(date) Checking $CHANNEL_URL" >> "$LOGFILE"

        # Skip if already recording
        if pgrep -f "ffmpeg.*${CHNAME}" >/dev/null || pgrep -f "yt-dlp.*${CHNAME}" >/dev/null; then
            echo "$(date) Already recording, skipping." >> "$LOGFILE"
            continue
        fi

        # Detect live stream URL
        STREAM_URL=$(yt-dlp --no-warnings --quiet -g "$CHANNEL_URL" 2>/dev/null | head -n 1)
        [ -z "$STREAM_URL" ] && continue

        # Check for DVR capability
        DVR_CHECK=$(curl -s "$STREAM_URL" | grep -m1 "EXT-X-PLAYLIST-TYPE:EVENT")

        TITLE=$(yt-dlp --print "%(title)s" "$CHANNEL_URL" 2>/dev/null | sed 's/[^a-zA-Z0-9._-]/_/g')
        DATE=$(date +"%Y-%m-%d_%H-%M-%S")
        FILENAME="${OUTDIR}/${DATE}_${TITLE}.mp4"

        echo "$(date) LIVE detected, recording to $FILENAME" >> "$LOGFILE"
        write_state "$OUTDIR" "recording"

        if [ -n "$DVR_CHECK" ]; then
            # DVR present — use ffmpeg
            ffmpeg -loglevel warning -i "$STREAM_URL" -c copy -metadata channel="$CHNAME" "$FILENAME" >> "$LOGFILE" 2>&1 &
        else
            # No DVR — use yt-dlp --live-from-start
            yt-dlp --live-from-start --merge-output-format mp4 --hls-use-mpegts -o "$FILENAME" "$CHANNEL_URL" >> "$LOGFILE" 2>&1 &
        fi

        sleep 5
    done < "$CHANNEL_LIST"

    sleep 30
done

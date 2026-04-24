#!/bin/bash
set -euo pipefail

mkdir -p "$(dirname "$CHANNEL_LIST")" "$BASE_DIR"
touch "$CHANNEL_LIST"

/app/auto-recorder.sh &
RECORDER_PID="$!"

gunicorn --bind 0.0.0.0:8090 --workers 2 --threads 4 dashboard.dashboard:app &
DASHBOARD_PID="$!"

shutdown() {
    kill "$RECORDER_PID" "$DASHBOARD_PID" 2>/dev/null || true
    wait "$RECORDER_PID" "$DASHBOARD_PID" 2>/dev/null || true
}
trap shutdown INT TERM

wait -n "$RECORDER_PID" "$DASHBOARD_PID"
shutdown

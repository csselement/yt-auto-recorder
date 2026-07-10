#!/usr/bin/env python3
"""Convert a yt-dlp JSON3 live-chat subtitle file into timestamped JSON Lines."""

import json
import sys
from pathlib import Path


def text_from_event(event: dict) -> str:
    segments = event.get("segs") or event.get("segments") or event.get("runs") or []
    parts = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get("utf8") or segment.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts).strip()


def author_from_event(event: dict):
    author = event.get("author") or event.get("authorName")
    if isinstance(author, dict):
        return author.get("name") or author.get("text")
    return author


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: chat-normalize.py INPUT.json3 OUTPUT.chat.jsonl", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Unable to read chat sidecar: {error}", file=sys.stderr)
        return 1

    events = payload.get("events", []) if isinstance(payload, dict) else []
    messages = []
    for event in events:
        if not isinstance(event, dict):
            continue
        text = text_from_event(event)
        if not text:
            continue
        messages.append({
            "time_ms": int(event.get("tStartMs", 0) or 0),
            "duration_ms": int(event.get("dDurationMs", 0) or 0),
            "text": text,
            "author": author_from_event(event),
            "type": "chat",
        })

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output:
        for message in messages:
            json.dump(message, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")

    print(len(messages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

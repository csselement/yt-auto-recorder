#!/usr/bin/env python3
import json
import os
import re
import tempfile
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

# Paths
CHANNEL_LIST = os.environ.get("CHANNEL_LIST", "/config/recording-channels.txt")
BASE_DIR = os.environ.get("BASE_DIR", "/recordings")

app = Flask(__name__)

def slugify(url: str) -> str:
    """
    Convert a URL into a safe directory name, matching auto-recorder.sh
    """
    u = url.replace("https://", "").replace("http://", "").replace("www.", "")
    return re.sub(r"[^A-Za-z0-9]+", "_", u).strip("_")

def ensure_channel_file() -> None:
    os.makedirs(os.path.dirname(CHANNEL_LIST), exist_ok=True)
    if not os.path.exists(CHANNEL_LIST):
        open(CHANNEL_LIST, "a").close()

def normalize_channel_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Channel URL is required.")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    allowed_hosts = {"youtube.com", "m.youtube.com", "youtu.be"}
    if host not in allowed_hosts and not host.endswith(".youtube.com"):
        raise ValueError("Only YouTube channel or livestream URLs can be watched.")

    return url

def read_channel_urls() -> list:
    ensure_channel_file()
    with open(CHANNEL_LIST, "r", encoding="utf-8") as f:
        urls = []
        for line in f:
            url = line.strip()
            if url and not url.startswith("#"):
                urls.append(url)
        return urls

def write_channel_urls(urls: list) -> None:
    ensure_channel_file()
    directory = os.path.dirname(CHANNEL_LIST)
    fd, temp_path = tempfile.mkstemp(prefix=".channels-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for url in urls:
                f.write(f"{url}\n")
        os.replace(temp_path, CHANNEL_LIST)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def load_state(chname: str):
    """
    Read the state.json file for a channel
    Returns: (status, last_seen)
    """
    state_file = os.path.join(BASE_DIR, chname, "state.json")
    if not os.path.exists(state_file):
        return ("monitoring", None)  # never seen

    try:
        with open(state_file, "r") as f:
            data = json.load(f)
            status = data.get("status", "monitoring")
            timestamp = data.get("timestamp")
            if not timestamp:
                timestamp = None
            return (status, timestamp)
    except Exception:
        return ("error", None)

def sort_channels(channels: list) -> list:
    """
    Sort channels by priority: recording → remuxing → monitoring → offline → error
    """
    priority = {
        "recording": 0,
        "remuxing": 1,
        "monitoring": 2,
        "offline": 3,
        "error": 4
    }
    return sorted(channels, key=lambda c: (priority.get(c["status"], 99), c["id"].lower()))

def load_channels() -> list:
    """
    Load all channels from CHANNEL_LIST with their current state
    """
    channels = []
    for url in read_channel_urls():
        chname = slugify(url)
        status, last_seen = load_state(chname)

        # Fix display for dashboard
        if last_seen is None or str(last_seen).lower() in ["unknown", "never"]:
            last_seen_display = "Never seen"
        elif status == "recording":
            last_seen_display = "Live now"
        else:
            last_seen_display = last_seen

        channels.append({
            "url": url,
            "id": chname,
            "status": status,
            "last_seen": last_seen_display
        })

    return sort_channels(channels)

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/status")
def status():
    return jsonify(load_channels())

@app.route("/channels", methods=["POST"])
def add_channel():
    payload = request.get_json(silent=True) or {}
    try:
        url = normalize_channel_url(payload.get("url", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    urls = read_channel_urls()
    existing = {item.rstrip("/").lower() for item in urls}
    if url.rstrip("/").lower() in existing:
        return jsonify({"error": "That channel is already being watched."}), 409

    urls.append(url)
    write_channel_urls(urls)
    return jsonify({"ok": True, "channels": load_channels()}), 201

@app.route("/channels", methods=["DELETE"])
def remove_channel():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url", "") or "").strip()
    if not url:
        return jsonify({"error": "Channel URL is required."}), 400

    urls = read_channel_urls()
    filtered = [item for item in urls if item.rstrip("/").lower() != url.rstrip("/").lower()]
    if len(filtered) == len(urls):
        return jsonify({"error": "That channel was not found."}), 404

    write_channel_urls(filtered)
    return jsonify({"ok": True, "channels": load_channels()})

if __name__ == "__main__":
    # Listen on all interfaces so LAN access works
    app.run(host="0.0.0.0", port=8090, debug=False)

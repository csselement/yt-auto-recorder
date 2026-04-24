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
SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "/config/settings.json")
DEFAULT_SETTINGS = {"channels": {}}

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

def coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

def ensure_settings_file() -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        write_settings(DEFAULT_SETTINGS)

def read_settings() -> dict:
    try:
        ensure_settings_file()
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    settings = DEFAULT_SETTINGS.copy()
    settings.update({k: data[k] for k in settings.keys() & data.keys()})
    if not isinstance(settings["channels"], dict):
        settings["channels"] = {}

    # Migrate the old global recording switch into per-channel settings.
    if "recording_active" in data and not settings["channels"]:
        active = coerce_bool(data["recording_active"])
        settings["channels"] = {url: {"active": active} for url in read_channel_urls()}

    for url, channel_settings in list(settings["channels"].items()):
        if not isinstance(channel_settings, dict):
            settings["channels"][url] = {"active": coerce_bool(channel_settings)}
        else:
            settings["channels"][url]["active"] = coerce_bool(channel_settings.get("active", True))
    return settings

def write_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    current = DEFAULT_SETTINGS.copy()
    current.update(settings)

    directory = os.path.dirname(SETTINGS_FILE)
    fd, temp_path = tempfile.mkstemp(prefix=".settings-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
            f.write("\n")
        os.replace(temp_path, SETTINGS_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def channel_is_active(url: str, settings: dict | None = None) -> bool:
    settings = settings or read_settings()
    return coerce_bool(settings.get("channels", {}).get(url, {}).get("active", True))

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
    settings = read_settings()
    for url in read_channel_urls():
        chname = slugify(url)
        status, last_seen = load_state(chname)
        active = channel_is_active(url, settings)

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
            "last_seen": last_seen_display,
            "active": active
        })

    return sort_channels(channels)

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/status")
def status():
    return jsonify(load_channels())

@app.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(read_settings())

@app.route("/settings", methods=["PATCH"])
def update_settings():
    return jsonify({"error": "Use PATCH /channels to update channel settings."}), 400

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
    settings = read_settings()
    settings.setdefault("channels", {}).setdefault(url, {"active": True})
    write_settings(settings)
    write_channel_urls(urls)
    return jsonify({"ok": True, "channels": load_channels()}), 201

@app.route("/channels", methods=["PATCH"])
def update_channel():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url", "") or "").strip()
    if not url:
        return jsonify({"error": "Channel URL is required."}), 400

    urls = read_channel_urls()
    match = next((item for item in urls if item.rstrip("/").lower() == url.rstrip("/").lower()), None)
    if not match:
        return jsonify({"error": "That channel was not found."}), 404

    updates = {}
    if "active" in payload:
        updates["active"] = coerce_bool(payload["active"])

    if not updates:
        return jsonify({"error": "No supported channel settings were provided."}), 400

    settings = read_settings()
    settings.setdefault("channels", {}).setdefault(match, {"active": True}).update(updates)
    write_settings(settings)
    return jsonify({"ok": True, "channels": load_channels()})

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
    settings = read_settings()
    settings.get("channels", {}).pop(url, None)
    settings["channels"] = {
        item_url: item_settings
        for item_url, item_settings in settings.get("channels", {}).items()
        if item_url.rstrip("/").lower() != url.rstrip("/").lower()
    }
    write_settings(settings)
    return jsonify({"ok": True, "channels": load_channels()})

if __name__ == "__main__":
    # Listen on all interfaces so LAN access works
    app.run(host="0.0.0.0", port=8090, debug=False)

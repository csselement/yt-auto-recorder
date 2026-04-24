# YouTube Live Auto Recorder

This runs a small web dashboard plus a background recorder that watches YouTube channel URLs. When a watched channel goes live, the recorder saves the livestream into that channel's folder.

This Docker image and Compose setup are written specifically for Ugreen NAS systems running the Ugreen Docker app. It may also work on other generic Docker or Docker Compose hosts, but the included NAS instructions and `docker-compose.ugreen.yml` are aimed at Ugreen NAS deployment.

## What Docker Does Here

Docker packages the recorder, dashboard, `yt-dlp`, `ffmpeg`, and their dependencies into one container. On your Ugreen NAS, you only need to run the container and mount two folders:

- `/config`: stores the watch list file.
- `/recordings`: stores downloaded livestream archives.

## Easy Ugreen Docker App Install

The easiest way to install this on a Ugreen NAS is to pull the published image from Docker Hub using the Ugreen NAS desktop Docker app.

1. Open the Ugreen NAS desktop.
2. Open the Docker app.
3. Click Image.
4. Search for:

```text
csselement/yt-auto-recorder
```

5. Pull the image from Docker Hub.
6. Create a container from the image.
7. Set the container port mapping:

```text
8090 -> 8090
```

8. Add two folder mappings:

```text
/config      stores the watch list
/recordings  stores the finished livestream recordings
```

9. Start the container.
10. Open the dashboard:

```text
http://NAS_IP_ADDRESS:8090
```

For example, if your NAS IP is `192.168.8.206`, open:

```text
http://192.168.8.206:8090
```

Use `http`, not `https`, unless you put this behind your own reverse proxy.

## Run Locally

From this folder:

```bash
docker compose up -d --build
```

If Docker Desktop is not running yet, start Docker Desktop first and wait until it says Docker is running.

Open:

```text
http://localhost:8090
```

The dashboard lets you add and remove YouTube channels from the watch list. Removing a channel only stops future watching; existing recordings stay on disk.

## Folders Created

With the included `docker-compose.yml`, files are stored here:

```text
./data/config/recording-channels.txt
./data/recordings/
```

For the NAS, change the left side of the two volume lines in `docker-compose.yml` to real folders on your Ugreen storage.

Example:

```yaml
volumes:
  - /volume1/docker/yt-auto-recorder/config:/config
  - /volume1/Recordings/YouTube:/recordings
```

## Ugreen Docker Compose Install

If you prefer using a Docker Compose project in the Ugreen Docker app, use `docker-compose.ugreen.yml`. The published image is:

```text
csselement/yt-auto-recorder:latest
```

In UGOS Pro:

1. Open Docker from the Ugreen NAS desktop.
2. Go to Project > Create.
3. Paste or upload the contents of `docker-compose.ugreen.yml`.
4. Click Deploy.
5. Open `http://NAS_IP_ADDRESS:8090`.

The NAS template uses project-relative folders:

```yaml
volumes:
  - ./config:/config
  - ./recordings:/recordings
```

This avoids Ugreen's "NAS path not found" validation error. If you want recordings in a specific shared folder, create that folder first in Ugreen File Manager, then replace `./recordings` with the real NAS path.

## Build Your Own Image

If you fork this project or want to publish your own Docker image, replace every `USERNAME` placeholder with your Docker Hub login name.

For example, if your Docker Hub login is `janedoe`, then:

```text
USERNAME/yt-auto-recorder:latest
```

becomes:

```text
janedoe/yt-auto-recorder:latest
```

Then build and push a multi-architecture image:

```bash
docker login
docker buildx create --use --name yt-auto-recorder-builder
docker buildx build --platform linux/amd64,linux/arm64 -t USERNAME/yt-auto-recorder:latest --push .
```

## Useful Commands

Start or update after edits:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f
```

Update `yt-dlp` by rebuilding:

```bash
docker compose build --no-cache
docker compose up -d
```

## Settings

These environment variables are available in `docker-compose.yml`:

- `CHECK_INTERVAL`: seconds between channel checks. Default is `30`.
- `CHANNEL_LIST`: path inside the container for the watch list.
- `BASE_DIR`: path inside the container for recordings.
- `VIDEO_CRF`: H.264 quality for finished MP4 files. Lower is higher quality/larger files. Default is `23`.
- `VIDEO_PRESET`: H.264 encoding speed. Default is `veryfast`.
- `AUDIO_BITRATE`: MP3 audio bitrate for finished MP4 files. Default is `192k`.

## Notes

- The dashboard listens on port `8090`.
- The recorder keeps one folder per watched channel under the recordings directory, with that channel's recordings saved inside it.
- If one channel is recording, other channels continue being checked.
- Active recordings are first written as `.mkv` files. When a stream ends, the archive is transcoded to H.264 `.mp4` with 192 kbps MP3 audio.

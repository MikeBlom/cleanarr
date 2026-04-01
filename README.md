# CleanArr

A web interface for browsing your Plex library and requesting automated content filtering — profanity muting, nudity blackout, and violence blackout — powered by [cleanmedia](https://github.com/MikeBlom/cleanmedia).

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Features

- **Plex integration** — browse libraries, view metadata, and request content filtering via Plex OAuth login
- **Customizable filtering** — per-request overrides for profanity words, nudity/violence confidence thresholds, and detection models
- **Background job processing** — queue-based worker processes filtering jobs using cleanmedia
- **AI content advisor** — optional Ollama integration to auto-evaluate content using IMDB parental guide data
- **Admin dashboard** — manage users, view job queue, configure settings at runtime
- **Multi-model ensemble** — NudeNet, ViT, SigLIP detectors with temporal consistency filtering
- **Docker-ready** — single `docker compose up` to get running

## Quick Start (Docker)

### 1. Clone the repository

```bash
git clone https://github.com/MikeBlom/cleanarr.git
cd cleanarr
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:
- `SECRET_KEY` — generate with `openssl rand -hex 32`
- `BASE_URL` — your server's URL
- `PLEX_CLIENT_ID` — generate with `python3 -c "import uuid; print(uuid.uuid4())"`
- `PLEX_SERVER_URL` — your Plex server address (e.g., `http://192.168.1.100:32400`)
- `PLEX_ADMIN_TOKEN` — your Plex admin token
- `PLEX_ADMIN_PLEX_IDS` — comma-separated Plex user IDs for admin access

### 3. Configure media mounts

Edit `docker-compose.yml` and uncomment/add volume mounts for your media directories:

```yaml
volumes:
  - ./app:/app/app
  - ./data:/data
  - /path/to/movies:/media/movies
  - /path/to/tv:/media/tv
  - /path/to/cleanmedia:/cleanmedia  # cleanmedia source for pip install
```

### 4. Start the application

```bash
docker compose up -d
```

### 5. Open the UI

Visit `http://localhost:8765` and log in with your Plex account.

## Configuration

CleanArr uses a two-tier configuration system:

- **Environment variables** (`.env`) — bootstrap settings loaded at startup: database URL, Plex credentials, secret key
- **Admin UI settings** (`/admin/settings`) — runtime-configurable: detection thresholds, model choices, profanity word lists, Ollama settings. Changes take effect immediately without restart.

## Requirements

- Docker and Docker Compose (recommended)
- A Plex Media Server
- [cleanmedia](https://github.com/MikeBlom/cleanmedia) (mounted as a volume or pre-installed in the image)

For the content filtering worker to function, the container needs access to your media files and sufficient resources to run ML models.

## CPU vs GPU

The default Docker image runs on **any machine** using CPU-only inference. This works out of the box — no special hardware required.

If you have an NVIDIA GPU, the CUDA image accelerates the ViT and SigLIP detectors by 5-10x. NudeNet uses ONNX Runtime and runs on CPU in both variants. Whisper (profanity detection) also benefits from GPU acceleration.

| Image | Base | Size | PyTorch | Use case |
|-------|------|------|---------|----------|
| `latest` | Ubuntu 22.04 | ~3-4 GB | CPU | Any machine |
| `latest-cuda` | NVIDIA CUDA 12.4 | ~9.5 GB | CUDA 12.4 | NVIDIA GPU |

### GPU Setup

Prerequisites:
- NVIDIA GPU with compatible drivers
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (`nvidia-container-toolkit`)

**Option A** — use the pre-built CUDA image:

```yaml
# docker-compose.yml
services:
  cleanarr:
    image: ghcr.io/mikeblom/cleanarr:latest-cuda
    # ... rest of your config
```

**Option B** — build locally with the compose override:

```bash
docker compose -f docker-compose.yml -f docker-compose.cuda.yml up -d --build
```

Verify GPU access:

```bash
docker exec cleanarr-cleanarr-1 python3 -c "import torch; print(torch.cuda.is_available())"
```

The `nudity_device` and `violence_device` settings in the admin UI default to `Auto`, which detects GPU availability at runtime. No configuration change is needed.

## Roadmap

- Multi-provider support (Emby, Jellyfin, local filesystem)
- Local authentication (username/password) as alternative to Plex OAuth
- Notification system for completed jobs
- User roles and permissions

## Related Projects

- [cleanmedia](https://github.com/MikeBlom/cleanmedia) — the CLI tool that performs the actual content detection and filtering

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

This project is licensed under the GPL-3.0 License. See [LICENSE](LICENSE) for details.

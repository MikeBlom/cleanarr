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
- `BASE_URL` — the public URL where CleanArr is accessible (e.g. `http://192.168.1.50:8765` for LAN access, or `https://clean.example.com` behind a reverse proxy). This is used for the Plex OAuth callback and determines whether session cookies are marked as secure.
- `PLEX_SERVER_URL` — your Plex server address (e.g. `http://192.168.1.50:32400`)
- `PLEX_ADMIN_TOKEN` — your Plex admin token ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/))
- `PLEX_ADMIN_PLEX_IDS` — comma-separated Plex user IDs for admin access

### 3. Configure media mounts

Edit `docker-compose.yml` and uncomment/add volume mounts for your media directories:

```yaml
volumes:
  - ./data:/data
  - /path/to/movies:/media/movies
  - /path/to/tv:/media/tv
```

### 4. Start the application

```bash
docker compose up -d
```

### 5. Open the UI

Visit your CleanArr instance at the `BASE_URL` you configured (default: `http://<your-server>:8765`) and sign in with your Plex account.

## Configuration

CleanArr uses a two-tier configuration system:

- **Environment variables** (`.env`) — bootstrap settings loaded at startup: database URL, Plex credentials, base URL
- **Admin UI settings** (`/admin/settings`) — runtime-configurable: detection thresholds, model choices, profanity word lists, Ollama settings. Changes take effect immediately without restart.

## Requirements

- Docker and Docker Compose
- A Plex Media Server

The [cleanmedia](https://github.com/MikeBlom/cleanmedia) CLI tool is bundled in the Docker image automatically. For development, you can override it by mounting a local copy at `/cleanmedia` (see `docker-compose.yml` comments).

For the content filtering worker to function, the container needs access to your media files and sufficient resources to run ML models.

## GPU Acceleration

The default Docker image runs on **any machine** using CPU-only inference — no special hardware required.

CleanArr's ML models (Whisper, ViT, SigLIP) run on [PyTorch](https://pytorch.org/), which supports multiple GPU backends. A GPU can accelerate these models by 5-10x. NudeNet uses ONNX Runtime and runs on CPU regardless of GPU availability.

| Model | Used for | GPU benefit |
|-------|----------|-------------|
| Whisper | Profanity detection (audio transcription) | Yes |
| ViT / SigLIP | Nudity and violence detection (image classification) | Yes |
| NudeNet | Nudity detection (body-part localization) | No (ONNX/CPU only) |

### NVIDIA CUDA (tested)

This is the tested and recommended GPU path. A pre-built CUDA Docker image is provided.

| Image | Base | Size | PyTorch | Use case |
|-------|------|------|---------|----------|
| `latest` | Ubuntu 22.04 | ~3-4 GB | CPU | Any machine |
| `latest-cuda` | NVIDIA CUDA 12.4 | ~9.5 GB | CUDA 12.4 | NVIDIA GPU |

**Prerequisites:**
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

**Verify GPU access:**

```bash
docker exec cleanarr-cleanarr-1 python3 -c "import torch; print(torch.cuda.is_available())"
```

The `nudity_device` and `violence_device` settings in the admin UI default to `Auto`, which detects NVIDIA GPU availability at runtime.

### AMD ROCm (untested)

PyTorch supports AMD GPUs via [ROCm](https://rocm.docs.amd.com/). To use this, you would need to build a custom Docker image using the [PyTorch ROCm wheels](https://pytorch.org/get-started/locally/) and an appropriate ROCm base image. The `nudity_device` / `violence_device` settings should be set to `cuda` in the admin UI (PyTorch uses the same device API for ROCm).

### Apple Metal / MPS (untested)

On macOS with Apple Silicon, PyTorch supports GPU acceleration via [Metal Performance Shaders](https://developer.apple.com/metal/). This applies to non-Docker setups (running the worker directly on macOS). PyTorch detects MPS automatically, but the current auto-detection in cleanmedia only checks for CUDA — you may need to configure the device manually.

### Intel (untested)

PyTorch has experimental support for Intel GPUs via [Intel Extension for PyTorch](https://github.com/intel/intel-extension-for-pytorch). This requires the appropriate PyTorch build and Intel oneAPI runtime.

## Roadmap

- Multi-provider support (Emby, Jellyfin)

## Related Projects

- [cleanmedia](https://github.com/MikeBlom/cleanmedia) — the CLI tool that performs the actual content detection and filtering. Can also be used standalone for local file processing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

This project is licensed under the GPL-3.0 License. See [LICENSE](LICENSE) for details.

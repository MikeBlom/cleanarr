# Contributing to CleanArr

Thanks for your interest in contributing!

## Development Setup

### With Docker (recommended)

```bash
git clone https://github.com/MikeBlom/cleanarr.git
cd cleanarr
cp .env.example .env
# Edit .env with your Plex details
docker compose up
```

The app mounts `./app` as a volume, so code changes are reflected immediately (uvicorn runs with reload in debug mode).

### Without Docker

```bash
git clone https://github.com/MikeBlom/cleanarr.git
cd cleanarr
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Plex details
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Code Style

This project uses [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
ruff check .
ruff format .
```

## Running Tests

```bash
pip install -e ".[test]" "passlib[bcrypt]"
pytest tests/ -v
```

Tests use an in-memory SQLite database and mock all external services (Plex, Ollama, SMTP). All tests should pass before submitting a PR — CI runs them automatically.

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run linting
5. Commit with a clear message
6. Open a pull request against `main`

## Reporting Issues

Please use [GitHub Issues](https://github.com/MikeBlom/cleanarr/issues) to report bugs or request features.

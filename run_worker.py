#!/usr/bin/env python3
"""Standalone worker — run on the host with the cleanmedia Python venv."""
import sys
import os

# Ensure the cleanarr app package is importable
sys.path.insert(0, os.path.dirname(__file__))

# Load .env from this directory
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.config import settings
from app.database import init_db
from app.worker import worker_loop

if __name__ == "__main__":
    print(f"CLEANMEDIA_BIN = {settings.CLEANMEDIA_BIN}", flush=True)
    print(f"DATABASE_URL   = {settings.DATABASE_URL}", flush=True)
    print("Initialising database…", flush=True)
    init_db()
    print("Worker starting…", flush=True)
    worker_loop()

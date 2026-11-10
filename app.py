"""Vercel entrypoint: Vercel's FastAPI detection looks for `app` in a root app.py."""
from backend.main import app  # noqa: F401

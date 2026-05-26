# Vercel ASGI entrypoint (api/index.py is a supported discovery path).
from main import app  # noqa: F401

__all__ = ["app"]

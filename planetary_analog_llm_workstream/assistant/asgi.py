"""ASGI entry point for `uvicorn assistant.asgi:app`."""

from assistant.api import create_app

app = create_app()

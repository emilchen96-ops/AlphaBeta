"""ASGI entry point."""

from alphadesk_api.app_factory import create_app

app = create_app()

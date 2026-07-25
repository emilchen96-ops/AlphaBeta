"""ASGI entry point."""

from alphadesk_api.app_factory import create_app, wrap_with_cors
from alphadesk_api.core.config import get_settings

settings = get_settings()
app = wrap_with_cors(create_app(settings), settings)

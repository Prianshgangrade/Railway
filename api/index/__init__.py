try:
	# Prefer FastAPI app for ASGI servers
	from .fastapi_app import app  # type: ignore
except Exception:
	# Fallback to nothing; deployment can still target fastapi_app:app explicitly
	app = None  # type: ignore

__all__ = ["app"]

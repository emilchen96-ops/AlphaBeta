# AlphaDesk API (M01)

FastAPI infrastructure shell for local development. It provides health, dependency status, structured logging, correlation IDs and a display-only WebSocket. It contains no trading-domain model or broker capability.

Install the pinned dependencies from `requirements.lock`, set `PYTHONPATH=src`, then run:

```text
uvicorn alphadesk_api.main:app --reload
```

The root repository README is the authoritative setup guide.

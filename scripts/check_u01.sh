#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose up --build -d
docker compose exec -T api alembic upgrade head
docker compose exec -T api python -m alphadesk_api.cli.demo initialize-research --mode fixture --json
docker compose exec -T api python -m alphadesk_api.cli.demo verify-research --json
python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/demo/research-status") as response:
    payload = json.load(response)
assert payload["status"] == "READY", payload
urllib.request.urlopen("http://127.0.0.1:5173/getting-started").read(1)
PY

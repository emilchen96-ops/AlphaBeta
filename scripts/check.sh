#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose config --quiet
docker compose run --rm api sh -c 'ruff check . && ruff format --check . && mypy src && pytest'
docker compose run --rm web sh -c 'npm run lint && npm run typecheck && npm run test && npm run build'

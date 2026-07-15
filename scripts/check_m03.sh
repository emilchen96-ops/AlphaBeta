#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."

docker compose config --quiet
docker compose --profile test up -d --wait postgres_test postgres redis
docker compose build api web
docker compose run --rm \
  -e ALPHADESK_RUN_INTEGRATION=true \
  -e ALPHADESK_RUN_M02_INTEGRATION=true \
  -e ALPHADESK_RUN_M03_INTEGRATION=true \
  api sh -c 'ruff check . && ruff format --check . && mypy src && alembic upgrade head && alembic current && alembic check && pytest'
docker compose run --rm web sh -c 'npm run lint && npm run typecheck && npm run test && npm run build'

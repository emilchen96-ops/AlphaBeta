#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."

docker compose up -d --wait postgres redis api
docker compose run --rm \
  -e ALPHADESK_EXTERNAL_FREE_MARKET_TESTS=true \
  api pytest -ra -m external tests/external
docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source AKSHARE_EASTMONEY
docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source BAOSTOCK

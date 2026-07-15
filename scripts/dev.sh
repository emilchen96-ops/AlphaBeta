#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."

if [ "${1:-up}" = "status" ]; then
  docker compose ps
else
  docker compose up --build -d
  docker compose ps
fi

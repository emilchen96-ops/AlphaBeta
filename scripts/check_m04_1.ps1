$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose --profile test up -d --wait postgres_test postgres redis
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose build api market_worker web
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm `
        -e ALPHADESK_RUN_INTEGRATION=true `
        -e ALPHADESK_RUN_M02_INTEGRATION=true `
        -e ALPHADESK_RUN_M03_INTEGRATION=true `
        -e ALPHADESK_RUN_M04_INTEGRATION=true `
        -e ALPHADESK_RUN_M04_1_INTEGRATION=true `
        api sh -c 'ruff check . && ruff format --check . && mypy src && alembic upgrade head && alembic current && alembic heads && alembic check && pytest -ra'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm web sh -c 'npm run lint && npm run typecheck && npm run test && npm run build'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

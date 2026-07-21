$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose exec -T api alembic upgrade head
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose exec -T api python -m alphadesk_api.cli.demo initialize-research --mode fixture --json
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose exec -T api python -m alphadesk_api.cli.demo verify-research --json
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Status = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/demo/research-status'
    if ($Status.status -ne 'READY') { throw "U01 verification returned $($Status.status)" }
    Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/getting-started' | Out-Null
}
finally {
    Pop-Location
}

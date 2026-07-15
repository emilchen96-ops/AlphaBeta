$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm api sh -c 'ruff check . && ruff format --check . && mypy src && pytest'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm web sh -c 'npm run lint && npm run typecheck && npm run test && npm run build'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

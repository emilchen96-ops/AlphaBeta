$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    docker compose up -d --wait postgres redis api
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm `
        -e ALPHADESK_EXTERNAL_FREE_MARKET_TESTS=true `
        api pytest -ra -m external tests/external
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source AKSHARE_EASTMONEY
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose run --rm api python -m alphadesk_api.cli.market_data provider-check --source BAOSTOCK
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

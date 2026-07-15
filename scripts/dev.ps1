param(
    [ValidateSet('up', 'status')]
    [string]$Action = 'up'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    if ($Action -eq 'status') {
        docker compose ps
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        exit 0
    }
    docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    docker compose ps
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

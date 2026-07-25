$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未找到 docker 命令。'
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker 当前未运行，AlphaDesk 已处于停止状态。' -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        exit 0
    }

    Write-Host '正在停止 AlphaDesk……' -ForegroundColor Cyan
    Push-Location $Root
    try {
        & docker compose stop
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose stop 执行失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    Write-Host ''
    Write-Host 'AlphaDesk 已停止，数据库和历史数据均已保留。' -ForegroundColor Green
    Start-Sleep -Seconds 2
    exit 0
}
catch {
    Write-Host ''
    Write-Host "停止失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

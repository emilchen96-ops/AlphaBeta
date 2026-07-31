$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$AgentPython = Join-Path $Root 'apps\api\.venv\Scripts\python.exe'
$AgentPidFile = Join-Path $Root 'work\miniqmt-agent.pid'

function Stop-MiniQMTAgent {
    if (-not (Test-Path -LiteralPath $AgentPidFile)) {
        return
    }

    $SavedPid = 0
    if (-not [int]::TryParse(
        (Get-Content -LiteralPath $AgentPidFile -Raw).Trim(),
        [ref]$SavedPid
    )) {
        Remove-Item -LiteralPath $AgentPidFile -Force
        return
    }

    $Process = Get-Process -Id $SavedPid -ErrorAction SilentlyContinue
    if ($Process) {
        try {
            if ($Process.Path -eq $AgentPython) {
                Write-Host '正在停止 MiniQMT 只读行情代理……' -ForegroundColor Cyan
                Stop-Process -Id $SavedPid -Force
            }
            else {
                Write-Host '代理 PID 已被其他程序占用，未停止该进程。' -ForegroundColor Yellow
            }
        }
        catch {
            Write-Host '无法确认代理进程路径，未停止该进程。' -ForegroundColor Yellow
        }
    }
    Remove-Item -LiteralPath $AgentPidFile -Force -ErrorAction SilentlyContinue
}

try {
    Stop-MiniQMTAgent

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

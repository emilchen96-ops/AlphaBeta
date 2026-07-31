param(
    [int]$StartupTimeoutSeconds = 180,
    [switch]$NoOpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$WebUrl = 'http://127.0.0.1:5173/'
$ApiHealthUrl = 'http://127.0.0.1:8000/health/live'
$MiniQMTStatusUrl = 'http://127.0.0.1:8000/api/v1/miniqmt/market-data/status'
$RuntimeDir = Join-Path $Root 'work'
$AgentPython = Join-Path $Root 'apps\api\.venv\Scripts\python.exe'
$AgentPidFile = Join-Path $RuntimeDir 'miniqmt-agent.pid'
$AgentStdoutLog = Join-Path $RuntimeDir 'miniqmt-agent.stdout.log'
$AgentStderrLog = Join-Path $RuntimeDir 'miniqmt-agent.stderr.log'

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-DockerEngine {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Start-DockerDesktopIfNeeded {
    if (Test-DockerEngine) {
        Write-Host 'Docker 已运行。' -ForegroundColor Green
        return
    }

    $Candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Docker\Docker Desktop.exe')
    )
    $DockerDesktop = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $DockerDesktop) {
        throw '未找到 Docker Desktop。请先安装或手动启动 Docker Desktop。'
    }

    Write-Host '正在启动 Docker Desktop，请稍候……' -ForegroundColor Yellow
    Start-Process -FilePath $DockerDesktop | Out-Null

    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            Write-Host 'Docker 已就绪。' -ForegroundColor Green
            return
        }
    }
    throw "Docker 在 $StartupTimeoutSeconds 秒内未能启动。"
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url,
        [datetime]$Deadline
    )

    while ((Get-Date) -lt $Deadline) {
        try {
            $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 400) {
                Write-Host "$Name 已就绪。" -ForegroundColor Green
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "$Name 在等待时间内未能就绪：$Url"
}

function Get-RunningMiniQMTAgent {
    if (-not (Test-Path -LiteralPath $AgentPidFile)) {
        return $null
    }

    $SavedPid = 0
    if (-not [int]::TryParse(
        (Get-Content -LiteralPath $AgentPidFile -Raw).Trim(),
        [ref]$SavedPid
    )) {
        return $null
    }

    $Process = Get-Process -Id $SavedPid -ErrorAction SilentlyContinue
    if (-not $Process) {
        return $null
    }
    try {
        if ($Process.Path -ne $AgentPython) {
            return $null
        }
    }
    catch {
        return $null
    }
    return $Process
}

function Start-MiniQMTAgent {
    if (-not (Test-Path -LiteralPath $AgentPython)) {
        Write-Host '未找到 API Python 环境，跳过 MiniQMT 行情代理。' -ForegroundColor Yellow
        return
    }

    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $RunningAgent = Get-RunningMiniQMTAgent
    if ($RunningAgent) {
        Write-Host "MiniQMT 行情代理已运行（PID $($RunningAgent.Id)）。" -ForegroundColor Green
        return
    }

    Remove-Item -LiteralPath $AgentPidFile -Force -ErrorAction SilentlyContinue
    $Agent = Start-Process `
        -FilePath $AgentPython `
        -ArgumentList @('-m', 'alphadesk_api.cli.miniqmt', 'run-agent') `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $AgentStdoutLog `
        -RedirectStandardError $AgentStderrLog `
        -PassThru
    Set-Content -LiteralPath $AgentPidFile -Value $Agent.Id -Encoding ascii

    $Deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $Deadline) {
        if ($Agent.HasExited) {
            Write-Host 'MiniQMT 行情代理启动后异常退出，请查看 work\miniqmt-agent.stderr.log。' -ForegroundColor Yellow
            return
        }
        try {
            $Status = Invoke-RestMethod -Uri $MiniQMTStatusUrl -TimeoutSec 3
            if ($Status.data.agent.state -eq 'CONNECTED') {
                Write-Host "MiniQMT 行情代理已连接（PID $($Agent.Id)）。" -ForegroundColor Green
                return
            }
        }
        catch {
            # API may briefly be unavailable while the agent is registering.
        }
        Start-Sleep -Seconds 1
    }

    Write-Host 'MiniQMT 行情代理已启动，但尚未连接。可继续使用已有历史数据；请确认 MiniQMT 已登录。' -ForegroundColor Yellow
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未找到 docker 命令。请确认 Docker Desktop 已正确安装。'
    }

    Write-Step '检查 Docker'
    Start-DockerDesktopIfNeeded

    Write-Step '启动 AlphaDesk 服务'
    Push-Location $Root
    try {
        & docker compose up -d
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up 启动失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    Write-Step '等待 FastAPI 和前端'
    $ServiceDeadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    Wait-HttpEndpoint -Name 'FastAPI' -Url $ApiHealthUrl -Deadline $ServiceDeadline
    Wait-HttpEndpoint -Name 'AlphaDesk 前端' -Url $WebUrl -Deadline $ServiceDeadline

    Write-Step '启动 MiniQMT 只读行情代理'
    Start-MiniQMTAgent

    if (-not $NoOpenBrowser) {
        Write-Step '打开 AlphaDesk'
        Start-Process $WebUrl | Out-Null
    }
    Write-Host '启动完成，可以关闭此窗口。' -ForegroundColor Green
    Start-Sleep -Seconds 2
    exit 0
}
catch {
    Write-Host ''
    Write-Host "AlphaDesk 启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    Write-Host '诊断信息：' -ForegroundColor Yellow
    Push-Location $Root
    try {
        & docker compose ps
    }
    catch {
        Write-Host '暂时无法读取 Docker 服务状态。'
    }
    finally {
        Pop-Location
    }
    exit 1
}

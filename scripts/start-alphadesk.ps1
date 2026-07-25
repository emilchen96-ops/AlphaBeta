param(
    [int]$StartupTimeoutSeconds = 180,
    [switch]$NoOpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$WebUrl = 'http://127.0.0.1:5173/'
$ApiHealthUrl = 'http://127.0.0.1:8000/health/live'

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

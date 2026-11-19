param(
    [string]$RepoPath = "C:\Users\RQ\Documents\Retriva-AI",
    [int]$Port = 8001,
    [switch]$EnableTestBug
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoPath)) {
    throw "Retriva repo not found: $RepoPath"
}

Push-Location $RepoPath
try {
    $dirty = git status --porcelain
    if ($dirty) {
        throw "Retriva working tree is dirty. Commit/stash changes before restarting."
    }

    git fetch origin main
    git checkout main
    git pull --ff-only origin main
    $sha = (git rev-parse HEAD).Trim()

    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match "python" -and $_.CommandLine -match "uvicorn.*api_server:app"
    }
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2

    $logDir = Join-Path $env:TEMP "retriva-api-logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $outLog = Join-Path $logDir "retriva-api.out.log"
    $errLog = Join-Path $logDir "retriva-api.err.log"

    $env:AWS_REGION = if ($env:AWS_REGION) { $env:AWS_REGION } else { "eu-north-1" }
    $env:AWS_PROFILE = if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "default" }
    $env:CLOUDWATCH_ENABLED = "true"
    $env:CLOUDWATCH_LOG_GROUP = "/opsflow/retriva-api"
    $env:CLOUDWATCH_LOG_STREAM = "retriva-api-local"
    $env:CLOUDWATCH_SEND_INTERVAL = "1"
    $env:SERVICE_NAME = "retriva-api"
    $env:ENVIRONMENT = "local"
    $env:GIT_COMMIT_SHA = $sha
    $env:ENABLE_TEST_BUG = if ($EnableTestBug) { "true" } else { "false" }

    $python = Join-Path $RepoPath ".venv\Scripts\python.exe"
    $process = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1", "--port", "$Port", "--lifespan", "off" `
        -WorkingDirectory $RepoPath `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru

    $deadline = (Get-Date).AddSeconds(30)
    do {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                Write-Host "Retriva restarted: pid=$($process.Id) commit=$sha http://127.0.0.1:$Port"
                Write-Host "Logs: $outLog"
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "Retriva did not become healthy. Check $errLog"
}
finally {
    Pop-Location
}

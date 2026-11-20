<#
.SYNOPSIS
    Inicia o Databricks GenieOps em portas/URL dedicada (sem conflitar com 8000/5173/8185/5185).
.EXAMPLE
    .\start.ps1           # Modo Single-Server em http://genieops.localhost:8765 (recomendado)
    .\start.ps1 -Dev      # Modo Dev: Frontend em http://genieops.localhost:5765 + API em :8765
    .\start.ps1 -Rebuild  # Recompila o frontend (web/dist) antes de subir no modo Single-Server
#>
param(
    [switch]$Dev,
    [switch]$Rebuild,
    [int]$ApiPort = 8765,
    [int]$UiPort = 5765
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$GenieOpsExe = Join-Path $Root ".venv\Scripts\genieops.exe"

if (-not (Test-Path $Python)) {
    Write-Error "Ambiente virtual .venv nao encontrado em $Python. Execute: python -m venv .venv && pip install -e '.[dev]'"
    exit 1
}

if ($Dev) {
    Write-Host "Iniciando Databricks GenieOps (Modo Dev)..." -ForegroundColor Cyan
    Write-Host "  Frontend: http://genieops.localhost:$UiPort  (ou http://127.0.0.1:$UiPort)" -ForegroundColor Green
    Write-Host "  Backend:  http://genieops.localhost:$ApiPort (Swagger: http://genieops.localhost:$ApiPort/docs)" -ForegroundColor Green

    $backendJob = Start-Process -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "genieops.web_api:create_app", "--factory", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort" `
        -WorkingDirectory $Root -PassThru -NoNewWindow

    try {
        Push-Location (Join-Path $Root "web")
        $env:VITE_API_TARGET = "http://127.0.0.1:$ApiPort"
        & npm.cmd run dev -- --port $UiPort
    }
    finally {
        Pop-Location
        if ($backendJob -and -not $backendJob.HasExited) {
            Stop-Process -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
else {
    $distIndex = Join-Path $Root "web\dist\index.html"
    if ($Rebuild -or -not (Test-Path $distIndex)) {
        Write-Host "Compilando frontend (web/dist)..." -ForegroundColor Cyan
        Push-Location (Join-Path $Root "web")
        try {
            & npm.cmd run build
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "Iniciando Databricks GenieOps (Single-Server)..." -ForegroundColor Cyan
    Write-Host "  App URL:  http://genieops.localhost:$ApiPort (ou http://127.0.0.1:$ApiPort)" -ForegroundColor Green
    Write-Host "  API Docs: http://genieops.localhost:$ApiPort/docs" -ForegroundColor Green
    & $GenieOpsExe serve --host 127.0.0.1 --port $ApiPort --no-browser
}

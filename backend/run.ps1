param([switch]$Build)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.env')) {
    python scripts/setup_env.py --local
    Write-Host 'Edita .env y agrega OLLAMA_API_KEY. Luego ejecuta .\run.ps1 nuevamente.'
    exit 0
}
if ($Build) { docker compose -f compose.yaml -f compose.local.yaml up --build -d }
else { docker compose -f compose.yaml -f compose.local.yaml up -d }
Write-Host 'Panel: http://localhost:8000/admin/login'
Write-Host 'Primera cuenta: docker compose exec api flask --app wsgi create-admin'

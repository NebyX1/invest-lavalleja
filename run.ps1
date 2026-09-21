[CmdletBinding()]
param(
  [ValidateSet('Dev', 'Preview')]
  [string]$Mode = 'Dev',
  [int]$Port = 4321,
  [bool]$OpenBrowser = $true
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Npm {
  param([string[]]$Arguments)
  & npm.cmd @Arguments
  if ($LASTEXITCODE -ne 0) { throw "npm $($Arguments -join ' ') falló con código $LASTEXITCODE." }
}

if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) { throw 'No se encontró Node.js en PATH.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'No se encontró npm en PATH.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules'))) { Invoke-Npm @('install') }

while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  Write-Warning "El puerto $Port está ocupado; se probará $($Port + 1) sin detener procesos ajenos."
  $Port++
}

if ($Mode -eq 'Preview') { Invoke-Npm @('run', 'build') }

$scriptName = if ($Mode -eq 'Preview') { 'preview' } else { 'dev' }
$logDirectory = Join-Path $PSScriptRoot 'reports'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stdoutPath = Join-Path $logDirectory "run-$Mode-out.log"
$stderrPath = Join-Path $logDirectory "run-$Mode-err.log"
$arguments = @('run', $scriptName, '--', '--host', '127.0.0.1', '--port', "$Port")
$process = Start-Process -FilePath 'npm.cmd' -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
$url = "http://127.0.0.1:$Port/"
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
  Start-Sleep -Milliseconds 250
  try {
    $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { $ready = $true; break }
  } catch { }
}

if (-not $ready) {
  $errorText = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { 'sin salida de error' }
  throw "Astro no respondió en $url. $errorText"
}

Write-Host "Invest Lavalleja $Mode listo en $url"
Write-Host "Logs: $stdoutPath y $stderrPath"
if ($OpenBrowser) { Start-Process $url }

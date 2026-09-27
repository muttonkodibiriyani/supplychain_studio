#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*$')]
    [string]$ProjectName = 'invoice-studio',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$NoBuild,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

# Development clones only: point git at the in-repo pre-push privacy guard so a
# push from this clone runs scripts/package_source.py --pre-push (the commits
# being pushed; --check-only is the manual pre-flight of the same range). Git never
# installs hooks on clone, so this is done here, on the first start. Idempotent,
# silent when already set, skipped in an unpacked source package (no .git).
if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git') -PathType Container) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $hooksPath = & git -C $PSScriptRoot config --get core.hooksPath 2>$null
    if ($hooksPath -ne '.githooks') {
        & git -C $PSScriptRoot config core.hooksPath .githooks
        Write-Host 'Installed the pre-push privacy guard for this clone (git config core.hooksPath .githooks).'
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker was not found. Follow docs/WINDOWS_SETUP.md, install Docker Desktop, then reopen PowerShell.'
}

$engine = & docker info --format '{{.OSType}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is not ready. Open Docker Desktop and wait for its engine to start, then try again.'
}
if ($engine.Trim() -ne 'linux') {
    throw 'Invoice Studio uses Linux containers. Select Linux containers in Docker Desktop, then try again.'
}

$previousPort = $env:INVOICE_HOST_PORT
Push-Location $PSScriptRoot
try {
    $env:INVOICE_HOST_PORT = [string]$Port
    & docker compose --project-name $ProjectName config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration failed.' }

    $running = & docker compose --project-name $ProjectName ps --status running --quiet 2>$null
    if (-not $running) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            throw "Port $Port is already in use by another program. Stop it, or rerun with: .\Start-InvoiceStudio.ps1 -Port 8010"
        }
    }

    $composeArgs = @('compose', '--project-name', $ProjectName, 'up', '--detach', '--wait', '--wait-timeout', '180')
    if (-not $NoBuild) { $composeArgs += '--build' }
    & docker @composeArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'Startup failed. Read the output above and the troubleshooting section in docs/WINDOWS_SETUP.md.'
    }

    Write-Host ''
    Write-Host "Workspace: $ProjectName"
    Write-Host "Open http://localhost:$Port"
    Write-Host 'Use this same project name on upgrades to retain your invoices and item master.'
    Write-Host 'For a different brand, choose both a different project name and an unused port.'
    & docker compose --project-name $ProjectName ps
    if (-not $NoBrowser) { Start-Process "http://localhost:$Port" }
}
finally {
    $env:INVOICE_HOST_PORT = $previousPort
    Pop-Location
}

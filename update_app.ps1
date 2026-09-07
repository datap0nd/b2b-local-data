# One update path: stop the running app, delegate to setup, then start the new release again.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Ref = 'main',
    [switch]$NoRestart
)
$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
if (-not $InstallDir) { $InstallDir = $here }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

function Read-Port {
    $port = 8765
    $envPath = Join-Path $InstallDir '.env'
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in Get-Content -LiteralPath $envPath) {
            if ($line -match '^\s*APP_PORT\s*=\s*"?(\d+)"?\s*$') { $port = [int]$Matches[1] }
        }
    }
    if ($env:APP_PORT -match '^\d+$') { $port = [int]$env:APP_PORT }
    return $port
}

function Stop-App([int]$Port) {
    $owners = @()
    try { $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique) } catch { }
    foreach ($processId in $owners) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -match '^python') {
            Write-Host "Stopping the running app (process $processId on port $Port)."
            Stop-Process -Id $processId -Force
        }
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        $busy = $false
        try { $busy = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop).Count -gt 0 } catch { }
        if (-not $busy) { return }
        Start-Sleep -Milliseconds 500
    }
}

$port = Read-Port
Stop-App $port
& (Join-Path $here 'setup.ps1') -InstallDir $InstallDir -Ref $Ref
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($NoRestart) { exit 0 }
# Start the refreshed release in its own window so this update console can finish.
$starter = Join-Path $InstallDir 'start.ps1'
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $starter, '-InstallDir', $InstallDir) -WorkingDirectory $InstallDir
Write-Host "Update finished; the app is starting in a new window at http://127.0.0.1:$port"
exit 0

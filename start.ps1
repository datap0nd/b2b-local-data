[CmdletBinding()]
param([string]$InstallDir)
$ErrorActionPreference = 'Stop'
# Resolve the install folder even when the script text was pasted into a console ($PSScriptRoot empty).
if (-not $InstallDir) { $InstallDir = $PSScriptRoot }
if (-not $InstallDir -and $PSCommandPath) { $InstallDir = Split-Path -Parent $PSCommandPath }
if (-not $InstallDir -and $MyInvocation.MyCommand.Path) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $InstallDir) { $InstallDir = (Get-Location).Path }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$service = Get-Service -Name 'B2BLocalData' -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne 'Running') {
        try {
            Start-Service -Name 'B2BLocalData' -ErrorAction Stop
            $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
        } catch {
            throw 'The B2BLocalData service is installed but stopped. Run update_app.ps1 so it can request Administrator access and repair it.'
        }
    }
    Write-Host 'B2B is already running as a Windows service.' -ForegroundColor Green
    Write-Host 'Local: http://127.0.0.1:8766'
    Get-NetIPConfiguration -ErrorAction SilentlyContinue |
        Where-Object IPv4DefaultGateway |
        ForEach-Object { Write-Host "Network: http://$($_.IPv4Address.IPAddress):8766" }
    exit 0
}
$pointer = Join-Path $InstallDir 'current.json'
if (Test-Path -LiteralPath $pointer) {
    $current = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $current.python) -or -not (Test-Path -LiteralPath (Join-Path $current.release 'run.py'))) {
        throw "The selected release in $pointer is missing. Run setup.ps1 in $InstallDir again."
    }
    & $current.python (Join-Path $current.release 'run.py') --home $InstallDir
} elseif (Test-Path -LiteralPath (Join-Path $InstallDir 'run.py')) {
    # Development checkout: use a Python already available to this user.
    & python (Join-Path $InstallDir 'run.py') --home $InstallDir
} else {
    throw "No installed release found in $InstallDir (current.json is missing). Run .\setup.ps1 there first, or pass -InstallDir <install folder>."
}
exit $LASTEXITCODE

# One update path: download, validate, install, and health-check the auto-starting Windows service.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Ref = "main",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$here = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
if (-not $InstallDir) { $InstallDir = $here }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdministrator) {
    if (-not $PSCommandPath) { throw "Run update_app.ps1 from its file so it can request Administrator access." }
    $arguments = @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
        "-InstallDir", "`"$InstallDir`"", "-Ref", "`"$Ref`""
    )
    if ($NoRestart) { $arguments += "-NoRestart" }
    Start-Process powershell.exe -ArgumentList ($arguments -join " ") -Verb RunAs
    exit 0
}

Write-Host "Updating B2B and refreshing its Windows service..." -ForegroundColor Cyan
$setupArguments = @{ InstallDir=$InstallDir; Ref=$Ref }
if ($NoRestart) { $setupArguments.NoServiceStart = $true }
& (Join-Path $here "setup.ps1") @setupArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($NoRestart) {
    Write-Host "Update finished. The B2BLocalData service is installed and stopped." -ForegroundColor Yellow
    exit 0
}

$service = Get-Service -Name "B2BLocalData" -ErrorAction SilentlyContinue
if (-not $service -or $service.Status -ne "Running") {
    throw "Update finished, but the B2BLocalData service is not running."
}

Write-Host "Update finished. B2B is running as an auto-starting Windows service." -ForegroundColor Green
Write-Host "Local: http://127.0.0.1:8766"
Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object IPv4DefaultGateway |
    ForEach-Object { Write-Host "Network: http://$($_.IPv4Address.IPAddress):8766" }
exit 0

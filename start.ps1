[CmdletBinding()]
param([string]$InstallDir)
$ErrorActionPreference = 'Stop'
# Resolve the install folder even when the script text was pasted into a console ($PSScriptRoot empty).
if (-not $InstallDir) { $InstallDir = $PSScriptRoot }
if (-not $InstallDir -and $PSCommandPath) { $InstallDir = Split-Path -Parent $PSCommandPath }
if (-not $InstallDir -and $MyInvocation.MyCommand.Path) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $InstallDir) { $InstallDir = (Get-Location).Path }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
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

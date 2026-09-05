[CmdletBinding()]
param([string]$InstallDir = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$pointer = Join-Path $InstallDir 'current.json'
if (Test-Path -LiteralPath $pointer) {
    $current = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    & $current.python (Join-Path $current.release 'run.py') --home $InstallDir
} else {
    # Development checkout: use a Python already available to this user.
    & python (Join-Path $PSScriptRoot 'run.py') --home $PSScriptRoot
}
exit $LASTEXITCODE

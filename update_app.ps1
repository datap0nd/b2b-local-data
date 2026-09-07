# One update path: delegate to setup instead of installing packages or compiling locally.
[CmdletBinding()]
param(
    [string]$InstallDir = $(if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'current.json')) { $PSScriptRoot } elseif ($env:B2B_INSTALL_ROOT) { $env:B2B_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA 'B2BLocalData' }),
    [string]$Ref = 'main'
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'setup.ps1') -InstallDir $InstallDir -Ref $Ref
exit $LASTEXITCODE

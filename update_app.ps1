# One update path: delegate to setup instead of installing packages or compiling locally.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Ref = 'main'
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'setup.ps1') -InstallDir $InstallDir -Ref $Ref
exit $LASTEXITCODE

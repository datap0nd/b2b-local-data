# One update path: delegate to setup instead of installing packages or compiling locally.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Ref = 'main'
)
$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
if (-not $InstallDir) { $InstallDir = $here }
& (Join-Path $here 'setup.ps1') -InstallDir $InstallDir -Ref $Ref
exit $LASTEXITCODE

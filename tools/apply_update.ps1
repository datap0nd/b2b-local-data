# Fixed local deployment entry point for an exact reviewed commit. No remote command API.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$Commit,
    [Parameter(Mandatory=$true)][string]$InstallDir
)
$ErrorActionPreference = 'Stop'
& (Join-Path (Split-Path $PSScriptRoot) 'setup.ps1') -InstallDir $InstallDir -Ref $Commit
exit $LASTEXITCODE

# Run from CI or locally. Only writes an isolated temporary installation.
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path $PSScriptRoot),
    [string]$TestRoot = (Join-Path ([IO.Path]::GetTempPath()) ('b2b-portable-test-' + [guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
New-Item -ItemType Directory -Path $TestRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceRoot 'setup.ps1') -Destination $TestRoot
Copy-Item -LiteralPath (Join-Path $SourceRoot '.env.example') -Destination $TestRoot
# No -InstallDir: emulate downloading the repo into a chosen folder, then running setup.
$first = @(& (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache (Join-Path $SourceRoot '.downloads'))
if ($LASTEXITCODE -ne 0) { throw 'First installation failed.' }
$selected = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if (-not $selected.release.StartsWith((Join-Path $TestRoot 'releases'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Setup did not install in its own folder.' }
Set-Content -LiteralPath (Join-Path $selected.release 'obsolete-test-code.py') -Value 'old release only'
Add-Content -LiteralPath (Join-Path $TestRoot '.env') -Value '# preserved local setting'
New-Item -ItemType Directory -Path (Join-Path $TestRoot 'data') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $TestRoot 'data\local-data-sentinel.txt') -Value 'preserve me'
$names = @('.env','business_rules.md','data\local-data-sentinel.txt')
$before = @{}
foreach ($name in $names) { $before[$name] = (Get-FileHash -LiteralPath (Join-Path $TestRoot $name)).Hash }
$second = @(& (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache (Join-Path $SourceRoot '.downloads') -Offline)
if ($LASTEXITCODE -ne 0) { throw 'Offline refresh failed.' }
$packageCount = (Get-Content -LiteralPath (Join-Path $SourceRoot 'dependencies.lock.json') -Raw | ConvertFrom-Json).packages.Count
if (($second -join "`n") -notmatch "Libraries: $packageCount reused, 0 unpacked, 0 downloaded") { throw 'Unchanged dependencies were not reused.' }
$refreshed = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if ($selected.release -eq $refreshed.release -or (Test-Path -LiteralPath (Join-Path $refreshed.release 'obsolete-test-code.py'))) { throw 'Application refresh retained obsolete code.' }
foreach ($name in $names) { if ($before[$name] -ne (Get-FileHash -LiteralPath (Join-Path $TestRoot $name)).Hash) { throw "Refresh changed local file: $name" } }
& $refreshed.python (Join-Path $refreshed.release 'updater.py') --home $TestRoot --rollback
if ($LASTEXITCODE -ne 0) { throw 'Rollback failed.' }
$rollback = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if ($rollback.release -ne $selected.release) { throw 'Rollback selected the wrong release.' }
Write-Output 'Portable folder install, offline reuse, clean code refresh, local data preservation, and rollback passed.'

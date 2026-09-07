# Run from CI or locally. Only writes an isolated temporary installation.
[CmdletBinding()]
param(
    [string]$SourceRoot = (Split-Path $PSScriptRoot),
    [string]$DownloadCache,
    [string]$TestRoot = (Join-Path ([IO.Path]::GetTempPath()) ('b2b-portable-test-' + [guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
if (-not $DownloadCache) { $DownloadCache = Join-Path $SourceRoot '.downloads' }
New-Item -ItemType Directory -Path $TestRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceRoot 'setup.ps1') -Destination $TestRoot
Copy-Item -LiteralPath (Join-Path $SourceRoot '.env.example') -Destination $TestRoot
# No -InstallDir: emulate downloading the repo into a chosen folder, then running setup.
$first = @(& (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache $DownloadCache)
if ($LASTEXITCODE -ne 0) { throw 'First installation failed.' }
$selected = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if (-not $selected.release.StartsWith((Join-Path $TestRoot 'releases'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Setup did not install in its own folder.' }
$envFile = Join-Path $TestRoot '.env'
$envText = [IO.File]::ReadAllText($envFile)
if ([regex]::Matches($envText, '(?mi)^B2B_ENABLE_ACCEPTANCE_UI=true\r?$').Count -ne 1) { throw 'Fresh install did not enable Test exactly once.' }
Set-Content -LiteralPath (Join-Path $selected.release 'obsolete-test-code.py') -Value 'old release only'
Add-Content -LiteralPath (Join-Path $TestRoot '.env') -Value '# preserved local setting'
New-Item -ItemType Directory -Path (Join-Path $TestRoot 'data') -Force | Out-Null
Set-Content -LiteralPath (Join-Path $TestRoot 'data\local-data-sentinel.txt') -Value 'preserve me'
$names = @('.env','business_rules.md','data\local-data-sentinel.txt')
$before = @{}
foreach ($name in $names) { $before[$name] = (Get-FileHash -LiteralPath (Join-Path $TestRoot $name)).Hash }
$second = @(& (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache $DownloadCache -Offline)
if ($LASTEXITCODE -ne 0) { throw 'Offline refresh failed.' }
$packageCount = (Get-Content -LiteralPath (Join-Path $SourceRoot 'dependencies.lock.json') -Raw | ConvertFrom-Json).packages.Count
if (($second -join "`n") -notmatch "Libraries: $packageCount reused, 0 unpacked, 0 downloaded") { throw 'Unchanged dependencies were not reused.' }
$refreshed = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if ($selected.release -eq $refreshed.release -or (Test-Path -LiteralPath (Join-Path $refreshed.release 'obsolete-test-code.py'))) { throw 'Application refresh retained obsolete code.' }
foreach ($name in $names) { if ($before[$name] -ne (Get-FileHash -LiteralPath (Join-Path $TestRoot $name)).Hash) { throw "Refresh changed local file: $name" } }
# Exercise the real setup transaction when --check fails after a missing-key migration.
# No credentials or production files are involved. A UTF-8 BOM/no-final-newline file
# must be restored byte-for-byte, and the selected release must remain unchanged.
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[IO.File]::WriteAllText($envFile, "# B2B_ENABLE_ACCEPTANCE_UI=false`r`nDB_KIND=invalid-fixture", $utf8Bom)
$failedConfigHash = (Get-FileHash -LiteralPath $envFile).Hash
$currentHash = (Get-FileHash -LiteralPath (Join-Path $TestRoot 'current.json')).Hash
$failedAsExpected = $false
try {
    & (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache $DownloadCache -Offline
    if ($LASTEXITCODE -ne 0) { $failedAsExpected = $true }
} catch {
    if ("$_" -notmatch 'Local configuration check failed') { throw }
    $failedAsExpected = $true
}
if (-not $failedAsExpected) { throw 'Invalid fixture configuration did not reject setup.' }
if ($failedConfigHash -ne (Get-FileHash -LiteralPath $envFile).Hash) { throw 'Failed setup did not restore exact .env bytes.' }
if ($currentHash -ne (Get-FileHash -LiteralPath (Join-Path $TestRoot 'current.json')).Hash) { throw 'Failed setup changed the selected release.' }
# The same missing-key shape must migrate successfully once the invalid value is corrected.
[IO.File]::WriteAllText($envFile, "# B2B_ENABLE_ACCEPTANCE_UI=false`r`nDB_KIND=demo", $utf8Bom)
$third = @(& (Join-Path $TestRoot 'setup.ps1') -LocalSource $SourceRoot -DownloadCache $DownloadCache -Offline)
if ($LASTEXITCODE -ne 0) { throw 'Missing-key upgrade failed.' }
$expectedEnv = $utf8Bom.GetPreamble() + $utf8Bom.GetBytes("# B2B_ENABLE_ACCEPTANCE_UI=false`r`nDB_KIND=demo`r`nB2B_ENABLE_ACCEPTANCE_UI=true`r`n")
if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($envFile)) -ne [Convert]::ToBase64String($expectedEnv)) { throw 'Missing-key upgrade did not preserve BOM, line endings, comments, or add Test exactly once.' }
# The last successful update retained the formerly selected release as rollback target.
& $refreshed.python (Join-Path $refreshed.release 'updater.py') --home $TestRoot --rollback
if ($LASTEXITCODE -ne 0) { throw 'Rollback failed.' }
$rollback = Get-Content -LiteralPath (Join-Path $TestRoot 'current.json') -Raw | ConvertFrom-Json
if ($rollback.release -ne $refreshed.release) { throw 'Rollback selected the wrong release.' }
Write-Output 'Portable folder install with Test enabled, missing-key upgrade, failed-config restoration, idempotent config, offline reuse, clean code refresh, local data preservation, and rollback passed.'

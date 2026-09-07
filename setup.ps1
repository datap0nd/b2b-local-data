# B2B Local Data: one setup/update entry point, portable Python, no pip or admin.
[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:B2B_INSTALL_ROOT) { $env:B2B_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA 'B2BLocalData' }),
    [string]$Repository = 'datap0nd/b2b-local-data',
    [string]$Ref = 'main',
    [string]$LocalSource,
    [string]$DownloadCache,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
if (-not $DownloadCache) { $DownloadCache = Join-Path $InstallDir '.downloads' }
$DownloadCache = [IO.Path]::GetFullPath($DownloadCache)
New-Item -ItemType Directory -Force -Path $DownloadCache | Out-Null
$setupLock = $null

function Download-File([string]$Url, [string]$Path, [hashtable]$Headers = @{}) {
    if ($Offline) { throw "Offline mode: missing required archive $([IO.Path]::GetFileName($Path))" }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -Headers $Headers -UseBasicParsing -TimeoutSec 90
            return
        } catch {
            if ($attempt -eq 3) { throw 'Download failed. Check access to GitHub, python.org, or the configured corporate proxy.' }
            Start-Sleep -Seconds 2
        }
    }
}

function Expand-CheckedArchive([string]$Archive, [string]$Target) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $resolved = [IO.Path]::GetFullPath((Join-Path $Target $entry.FullName))
            if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid path in downloaded archive.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Target)
}

try {
    # A second setup must not overwrite current.json while another setup is testing.
    $setupLock = [IO.File]::Open((Join-Path $InstallDir '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $installId = [guid]::NewGuid().ToString('N')
    if ($LocalSource) {
        $source = [IO.Path]::GetFullPath($LocalSource)
        $commit = 'local'
    } else {
        if ($Offline) { throw 'For offline setup, provide -LocalSource and a populated -DownloadCache.' }
        if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repository must use owner/name format.' }
        $headers = @{ 'User-Agent'='B2B-Local-Data-Setup'; 'Accept'='application/vnd.github+json' }
        if ($env:B2B_GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:B2B_GITHUB_TOKEN" }
        $encodedRef = [uri]::EscapeDataString($Ref)
        $commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/commits/$encodedRef" -Headers $headers -TimeoutSec 30).sha
        if ($commit -notmatch '^[a-f0-9]{40}$') { throw 'GitHub did not return an exact commit.' }
        Write-Host "Downloading $Repository at $commit"
        $archive = Join-Path $DownloadCache "$commit-$installId.zip"
        Download-File "https://api.github.com/repos/$Repository/zipball/$commit" $archive $headers
        $extracted = Join-Path $DownloadCache "source-$installId"
        Expand-CheckedArchive $archive $extracted
        $folders = @(Get-ChildItem -LiteralPath $extracted -Directory)
        if ($folders.Count -ne 1) { throw 'Unexpected repository archive layout.' }
        $source = $folders[0].FullName
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'run.py'))) { throw 'Source folder must contain run.py.' }
    $release = Join-Path $InstallDir "releases\$commit-$installId"
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    # Copy only shipped source. .env, local schema/rules, incoming scripts and data stay outside releases.
    foreach ($item in @('web','config','scripts','tests','migrations','tools','app_config.py','data_layer.py','history_store.py','query_models.py','query_engine.py','ui_app.py','updater.py','run_app.py','run.py','VERSION','README.md','.env.example','release_manifest.json','dependencies.lock.json','runtime.lock.json','setup.ps1','start.ps1','update_app.ps1')) {
        Copy-Item -LiteralPath (Join-Path $source $item) -Destination $release -Recurse
    }
    $runtime = Get-Content -LiteralPath (Join-Path $release 'runtime.lock.json') -Raw | ConvertFrom-Json
    $runtimeDir = Join-Path $InstallDir "runtime\python-$($runtime.version)-amd64"
    $python = Join-Path $runtimeDir 'python.exe'
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir '.ready'))) {
        if (Test-Path -LiteralPath $runtimeDir) {
            # Do not reuse partially extracted runtime files; leave them available for inspection.
            $runtimeDir = "$runtimeDir-$installId"
            $python = Join-Path $runtimeDir 'python.exe'
        }
        $pythonZip = Join-Path $DownloadCache $runtime.filename
        $valid = (Test-Path -LiteralPath $pythonZip) -and ((Get-FileHash -LiteralPath $pythonZip -Algorithm SHA256).Hash -eq $runtime.sha256)
        if (-not $valid) { Download-File $runtime.url $pythonZip }
        if ((Get-FileHash -LiteralPath $pythonZip -Algorithm SHA256).Hash -ne $runtime.sha256) { throw 'Python archive checksum mismatch.' }
        Expand-CheckedArchive $pythonZip $runtimeDir
        & $python -c 'import sqlite3, ssl, http.server; print("Portable Python ready")'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python could not start on this PC.' }
        Set-Content -LiteralPath (Join-Path $runtimeDir '.ready') -Value $runtime.sha256
    }
    $vendorArgs = @((Join-Path $release 'scripts\vendor_dependencies.py'), '--cache', $DownloadCache)
    if ($Offline) { $vendorArgs += '--offline' }
    & $python @vendorArgs
    if ($LASTEXITCODE -ne 0) { throw 'Dependency download or verification failed.' }
    & $python (Join-Path $release 'run.py') --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Release checks failed; the previous release is still selected.' }
    foreach ($pair in @(@('.env.example','.env'), @('config\business_rules.example.md','business_rules.md'))) {
        $target = Join-Path $InstallDir $pair[1]
        if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath (Join-Path $release $pair[0]) -Destination $target }
    }
    & $python (Join-Path $release 'run.py') --home $InstallDir --check
    if ($LASTEXITCODE -ne 0) { throw 'Local configuration check failed; the previous release is still selected.' }
    [IO.File]::WriteAllText((Join-Path $release '.release.json'), (@{commit=$commit} | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    $pointer = @{ release=$release; python=$python; commit=$commit; installed_at=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json
    $pending = Join-Path $InstallDir "current-$installId.json"
    [IO.File]::WriteAllText($pending, $pointer, (New-Object System.Text.UTF8Encoding($false)))
    $current = Join-Path $InstallDir 'current.json'
    if (Test-Path -LiteralPath $current) { [IO.File]::Replace($pending, $current, (Join-Path $InstallDir 'previous.json')) }
    else { [IO.File]::Move($pending, $current) }
    Copy-Item -LiteralPath (Join-Path $release 'start.ps1') -Destination (Join-Path $InstallDir 'start.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $release 'setup.ps1') -Destination (Join-Path $InstallDir 'setup.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $release 'update_app.ps1') -Destination (Join-Path $InstallDir 'update_app.ps1') -Force
    Write-Host "Ready: $InstallDir"
    Write-Host 'Edit .env and business_rules.md here. Existing settings and conversation data were preserved.'
    Write-Host 'Run start.ps1. If the app is already running, stop it with Ctrl+C and start it again to use this release.'
} catch {
    Write-Error $_
    exit 1
} finally {
    if ($setupLock) { $setupLock.Dispose() }
}

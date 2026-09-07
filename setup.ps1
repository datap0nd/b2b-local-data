# Download/refresh this folder from GitHub; portable Python and libraries, no pip.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Repository = 'datap0nd/b2b-local-data',
    [string]$Ref = 'main',
    [string]$LocalSource,
    [string]$DownloadCache,
    [switch]$Offline,
    [ValidatePattern('^(local|[a-f0-9]{40})$')][string]$SourceCommit = 'local'
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Read-EnvFile([string]$Path) {
    $values = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($raw in [IO.File]::ReadAllLines($Path)) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith('#')) { continue }
            if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { throw 'Invalid .env entry. Use KEY=value lines.' }
            $key = $Matches[1]; $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value = $value.Substring(1, $value.Length - 2) }
            $values[$key] = $value
        }
    }
    return $values
}
function Setting([string]$Key, [hashtable]$Values) {
    if (Test-Path -LiteralPath "Env:$Key") { return [Environment]::GetEnvironmentVariable($Key) }
    return $Values[$Key]
}

$bootstrapValues = Read-EnvFile (Join-Path $PSScriptRoot '.env')
if (-not $InstallDir) { $InstallDir = Setting 'B2B_INSTALL_ROOT' $bootstrapValues }
if (-not $InstallDir) { $InstallDir = $PSScriptRoot }
if (-not [IO.Path]::IsPathRooted($InstallDir)) { $InstallDir = Join-Path $PSScriptRoot $InstallDir }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
# A downloaded repo can supply the template before private-repository authentication.
$envPath = Join-Path $InstallDir '.env'
if (-not (Test-Path -LiteralPath $envPath) -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env.example'))) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination $envPath
}
$localValues = Read-EnvFile $envPath
# PAT_CODE is the data-governance GitHub token: a process/user environment variable, or a .env line.
$githubToken = Setting 'PAT_CODE' $localValues
if (-not $githubToken) { $githubToken = Setting 'B2B_GITHUB_TOKEN' $localValues }   # legacy name from earlier installs
$githubHeaders = @{ 'User-Agent'='B2B-Local-Data-Setup'; 'Accept'='application/vnd.github+json'; 'X-GitHub-Api-Version'='2022-11-28' }
if ($githubToken) { $githubHeaders['Authorization'] = "Bearer $githubToken" }
if (-not $DownloadCache) { $DownloadCache = Join-Path $InstallDir '.downloads' }
$DownloadCache = [IO.Path]::GetFullPath($DownloadCache)
New-Item -ItemType Directory -Force -Path $DownloadCache | Out-Null
$setupLock = $null
$script:releaseAssets = $null
$script:archiveDownloads = 0
$script:archiveReused = 0

function Download-File([string]$Url, [string]$Path, [hashtable]$Headers) {
    if ($Offline) { throw "Offline mode: missing required archive $([IO.Path]::GetFileName($Path))" }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -Headers $Headers -UseBasicParsing -TimeoutSec 120
            return
        } catch {
            if ($attempt -eq 3) { throw 'GitHub download failed. Check access and the PAT_CODE token.' }
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
function Get-LockedArchive($Item, [string]$Tag) {
    if ([IO.Path]::GetFileName($Item.filename) -ne $Item.filename -or $Item.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid portable archive lock.' }
    $archivePath = Join-Path $DownloadCache $Item.filename
    if ((Test-Path -LiteralPath $archivePath) -and (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -eq $Item.sha256) {
        $script:archiveReused++
        return $archivePath
    }
    if ($Offline) { throw "Offline mode: missing or invalid cached archive $($Item.filename)" }
    if (-not $script:releaseAssets) {
        try { $script:releaseAssets = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/tags/$Tag" -Headers $githubHeaders -TimeoutSec 30).assets }
        catch { throw 'Portable GitHub release is unavailable. Check the PAT_CODE token and that this release has been published.' }
    }
    $asset = @($script:releaseAssets | Where-Object { $_.name -ceq $Item.filename -and $_.state -eq 'uploaded' })
    if ($asset.Count -ne 1 -or "$($asset[0].id)" -notmatch '^[0-9]+$') { throw "Portable release is missing $($Item.filename)." }
    Write-Host "Downloading dependency from GitHub: $($Item.filename)"
    $binaryHeaders = $githubHeaders.Clone(); $binaryHeaders['Accept'] = 'application/octet-stream'
    $downloadUrl = "https://api.github.com/repos/$Repository/releases/assets/$($asset[0].id)?cache=$([guid]::NewGuid().ToString('N'))"
    Download-File $downloadUrl $archivePath $binaryHeaders
    if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $Item.sha256) { throw "Archive checksum mismatch: $($Item.filename)" }
    $script:archiveDownloads++
    return $archivePath
}

try {
    if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repository must use owner/name format.' }
    $setupLock = [IO.File]::Open((Join-Path $InstallDir '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $installId = [guid]::NewGuid().ToString('N')
    if ($LocalSource) {
        $source = [IO.Path]::GetFullPath($LocalSource)
        $commit = $SourceCommit
    } else {
        if ($Offline) { throw 'For offline setup, provide -LocalSource and a populated -DownloadCache.' }
        $encodedRef = [uri]::EscapeDataString($Ref)
        try { $commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/commits/${encodedRef}?cache=$installId" -Headers $githubHeaders -TimeoutSec 30).sha }
        catch { throw 'Cannot read GitHub main/ref. For this private repository, provide the PAT_CODE token as an environment variable or in the local .env.' }
        if ($commit -notmatch '^[a-f0-9]{40}$') { throw 'GitHub did not return an exact commit.' }
        Write-Host "Refreshing application from $Repository at $commit"
        $archive = Join-Path $DownloadCache "$commit-$installId.zip"
        Download-File "https://api.github.com/repos/$Repository/zipball/$commit" $archive $githubHeaders
        $extracted = Join-Path $DownloadCache "source-$installId"
        Expand-CheckedArchive $archive $extracted
        $folders = @(Get-ChildItem -LiteralPath $extracted -Directory)
        if ($folders.Count -ne 1) { throw 'Unexpected repository archive layout.' }
        $source = $folders[0].FullName
        # Run installer fixes from the downloaded revision during this same update.
        $freshSetup = Join-Path $source 'setup.ps1'
        if ((Get-FileHash -LiteralPath $freshSetup).Hash -ne (Get-FileHash -LiteralPath $PSCommandPath).Hash) {
            $setupLock.Dispose(); $setupLock = $null
            Write-Host 'Continuing with the freshly downloaded setup.ps1.'
            & $freshSetup -InstallDir $InstallDir -Repository $Repository -LocalSource $source -SourceCommit $commit -DownloadCache $DownloadCache
            if ($LASTEXITCODE -ne 0) { throw 'Updated setup script failed.' }
            return
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'run.py'))) { throw 'Source folder must contain run.py.' }
    $release = Join-Path $InstallDir "releases\$commit-$installId"
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    # A clean directory means code removed from main cannot linger in the running app.
    # Local configuration/data and dependency caches are not part of application code.
    $preserved = @('.git','.local','.downloads','.test-postgres','.venv','runtime','dependencies','releases','vendor','data','incoming','__pycache__','.env','schema.json','business_rules.md','current.json','previous.json','.release.json','.setup.lock')
    foreach ($item in Get-ChildItem -LiteralPath $source -Force) {
        if ($item.Name -in $preserved -or $item.Name -like '.install-test*' -or $item.Name -like 'vendor.*' -or ($item.Name -like '.env.*' -and $item.Name -ne '.env.example')) { continue }
        Copy-Item -LiteralPath $item.FullName -Destination $release -Recurse
    }
    $runtime = Get-Content -LiteralPath (Join-Path $release 'runtime.lock.json') -Raw | ConvertFrom-Json
    $dependencies = Get-Content -LiteralPath (Join-Path $release 'dependencies.lock.json') -Raw | ConvertFrom-Json
    $assets = Get-Content -LiteralPath (Join-Path $release 'portable_assets.lock.json') -Raw | ConvertFrom-Json
    if ($assets.release_tag -notmatch '^portable-[A-Za-z0-9_.-]+$' -or $assets.format -ne 1) { throw 'Invalid portable GitHub release lock.' }
    foreach ($pair in @(@('runtime.lock.json','runtime_lock_sha256'), @('dependencies.lock.json','dependency_lock_sha256'))) {
        if ((Get-FileHash -LiteralPath (Join-Path $release $pair[0])).Hash -ne $assets.($pair[1])) { throw 'Portable release and dependency locks differ.' }
    }
    $pythonZip = Get-LockedArchive $runtime $assets.release_tag
    $runtimeDir = Join-Path $InstallDir "runtime\python-$($runtime.version)-amd64"
    $python = Join-Path $runtimeDir 'python.exe'
    $ready = Join-Path $runtimeDir '.ready'
    $runtimeValid = (Test-Path -LiteralPath $ready) -and (Test-Path -LiteralPath $python) -and ((Get-Content -LiteralPath $ready -Raw).Trim() -eq $runtime.sha256)
    if ($runtimeValid) {
        & $python -c 'import sqlite3, ssl, http.server' 2>$null
        $runtimeValid = $LASTEXITCODE -eq 0
    }
    if (-not $runtimeValid) {
        if (Test-Path -LiteralPath $runtimeDir) { $runtimeDir = "$runtimeDir-$installId"; $python = Join-Path $runtimeDir 'python.exe' }
        Expand-CheckedArchive $pythonZip $runtimeDir
        & $python -c 'import sqlite3, ssl, http.server; print(''Portable Python ready'')'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python could not start on this PC.' }
        Set-Content -LiteralPath (Join-Path $runtimeDir '.ready') -Value $runtime.sha256
    } else { Write-Host 'Reusing portable Python.' }
    foreach ($package in $dependencies.packages) { $null = Get-LockedArchive $package $assets.release_tag }
    Write-Host "Dependency archives: $script:archiveReused reused, $script:archiveDownloads downloaded."
    # No network access or pip in the extraction step. Setup has fetched GitHub assets.
    & $python (Join-Path $release 'scripts\vendor_dependencies.py') --cache $DownloadCache --store (Join-Path $InstallDir 'dependencies') --offline
    if ($LASTEXITCODE -ne 0) { throw 'Local dependency extraction or verification failed.' }
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
    foreach ($name in @('start.ps1','setup.ps1','update_app.ps1')) { Copy-Item -LiteralPath (Join-Path $release $name) -Destination (Join-Path $InstallDir $name) -Force }
    Write-Host "Ready in this folder: $InstallDir"
    Write-Host "Active application: $release"
    Write-Host 'Local .env, business rules, and conversation/data files were preserved.'
    Write-Host 'Run start.ps1. After an update, stop the running app with Ctrl+C and start it again.'
} catch {
    Write-Error $_
    exit 1
} finally {
    if ($setupLock) { $setupLock.Dispose() }
}

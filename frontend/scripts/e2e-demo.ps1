param(
    [string]$Python = 'python',
    [int]$Port = 8765,
    [string]$DataHome = '',
    [string[]]$PlaywrightArgs = @()
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if (-not $DataHome) {
    $tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
    $DataHome = Join-Path $tempRoot 'b2b-browser-tests'
}
$e2eHome = [System.IO.Path]::GetFullPath($DataHome)
New-Item -ItemType Directory -Force -Path $e2eHome | Out-Null
$pythonPath = (Get-Command $Python -ErrorAction Stop).Source
$outputLog = Join-Path $e2eHome 'server-output.log'
$errorLog = Join-Path $e2eHome 'server-error.log'
$baseUrl = "http://127.0.0.1:$Port"
$savedEnvironment = @{}
foreach ($key in @('DB_KIND', 'B2B_ENABLE_ACCEPTANCE_UI', 'B2B_ALLOW_LOCALHOST_IDENTITY', 'APP_PORT', 'B2B_E2E_URL')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$server = $null
$browserExit = 1

try {
    $env:DB_KIND = 'demo'
    $env:B2B_ENABLE_ACCEPTANCE_UI = 'true'
    $env:B2B_ALLOW_LOCALHOST_IDENTITY = 'false'
    $env:APP_PORT = [string]$Port
    $env:B2B_E2E_URL = $baseUrl

    # Keep the server and browser runner in one process lifetime. A detached server can be
    # terminated when a Windows Actions step closes, even after its readiness check passed.
    $launcherPath = Join-Path $repoRoot 'run.py'
    $server = Start-Process -FilePath $pythonPath -ArgumentList @('"' + $launcherPath + '"', '--home', '"' + $e2eHome + '"') -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $server.Refresh()
        if ($server.HasExited) { throw "Demo backend exited before readiness (exit $($server.ExitCode))." }
        try {
            Invoke-WebRequest "$baseUrl/api/bootstrap" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Demo backend did not become ready.' }

    Push-Location (Join-Path $repoRoot 'frontend')
    try {
        & npm.cmd run e2e -- @PlaywrightArgs
        $browserExit = $LASTEXITCODE
    } finally { Pop-Location }
} catch {
    if (Test-Path -LiteralPath $errorLog) { Get-Content -LiteralPath $errorLog }
    throw
} finally {
    if ($server) {
        $server.Refresh()
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
        $server.Dispose()
    }
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process') }
}

exit $browserExit

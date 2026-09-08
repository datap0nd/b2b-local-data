[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [ValidateRange(1, 65535)][int]$Port = 8766,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$serviceName = "B2BLocalData"
$displayName = "B2B Salesforce Query Agent"
$ruleName = "B2B Local Data TCP $Port"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Installing the B2B Windows service requires Administrator PowerShell."
}

$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$ReleaseDir = [IO.Path]::GetFullPath($ReleaseDir)
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
$runScript = Join-Path $ReleaseDir "run.py"
$nssm = Join-Path $ReleaseDir "tools\nssm.exe"
$logDir = Join-Path $InstallDir "logs"

foreach ($required in @($PythonExe, $runScript, $nssm)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "The service dependency is missing: $required"
    }
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing -and $existing.Status -ne "Stopped") {
    & $nssm stop $serviceName | Out-Null
    try {
        $existing.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    } catch {
        throw "The existing B2B service did not stop within 30 seconds."
    }
}

$serviceArguments = "`"$runScript`" --home `"$InstallDir`" --host 0.0.0.0 --port $Port"
if (-not $existing) {
    & $nssm install $serviceName $PythonExe $serviceArguments
    if ($LASTEXITCODE -ne 0) { throw "NSSM could not install the B2B service." }
}

& $nssm set $serviceName Application $PythonExe | Out-Null
& $nssm set $serviceName AppParameters $serviceArguments | Out-Null
& $nssm set $serviceName AppDirectory $ReleaseDir | Out-Null
& $nssm set $serviceName DisplayName $displayName | Out-Null
& $nssm set $serviceName Description "LAN-accessible B2B Salesforce analytics application" | Out-Null
& $nssm set $serviceName Start SERVICE_AUTO_START | Out-Null
& $nssm set $serviceName AppExit Default Restart | Out-Null
& $nssm set $serviceName AppRestartDelay 5000 | Out-Null
$serviceEnvironmentByName = @{}
foreach ($item in Get-ChildItem Env:) {
    if ($item.Name -match "^(B2B_|DB_|PG|RO_SQL_|LLM_|LOCAL_AI_|DG_AI_|AI_)") {
        $serviceEnvironmentByName[$item.Name.ToUpperInvariant()] = "$($item.Value)"
    }
}
$serviceEnvironmentByName["B2B_LISTEN_HOST"] = "0.0.0.0"
$serviceEnvironmentByName["APP_PORT"] = "$Port"
$serviceEnvironment = @($serviceEnvironmentByName.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" })
& $nssm set $serviceName AppEnvironmentExtra @serviceEnvironment | Out-Null
& $nssm set $serviceName AppStdout (Join-Path $logDir "b2b.log") | Out-Null
& $nssm set $serviceName AppStderr (Join-Path $logDir "b2b_error.log") | Out-Null
& $nssm set $serviceName AppStdoutCreationDisposition 4 | Out-Null
& $nssm set $serviceName AppStderrCreationDisposition 4 | Out-Null
& $nssm set $serviceName AppRotateFiles 1 | Out-Null
& $nssm set $serviceName AppRotateSeconds 86400 | Out-Null
& $nssm set $serviceName AppRotateBytes 10485760 | Out-Null

$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
    $existingRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port | Out-Null
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
}

if ($NoStart) {
    Write-Host "B2B service installed on TCP $Port and left stopped."
    exit 0
}

& $nssm start $serviceName | Out-Null
$service = Get-Service -Name $serviceName -ErrorAction Stop
try {
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
} catch {
    throw "The B2B service did not reach Running. Check $logDir\b2b_error.log."
}

$healthy = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
}

if (-not $healthy) {
    throw "The B2B service is running but localhost did not answer on port $Port. Check $logDir\b2b_error.log."
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
if (-not @($listener | Where-Object { $_.LocalAddress -in @("0.0.0.0", "::") }).Count) {
    throw "B2B answered locally but is not listening on all network interfaces."
}

Write-Host "B2B service is running and listening on 0.0.0.0:$Port." -ForegroundColor Green
Write-Host "Local:   http://127.0.0.1:$Port"
$addresses = @(Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | ForEach-Object { $_.IPv4Address.IPAddress })
foreach ($address in $addresses) {
    Write-Host "Network: http://${address}:$Port"
}

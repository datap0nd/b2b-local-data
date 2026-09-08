# Start on the LOCAL capture PC, never on the work PC.
$captureRoot = $PSScriptRoot
$captureCandidates = @(
    (Join-Path $captureRoot '.install-test/runtime/python-3.13.15-amd64/python.exe'),
    (Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
)
$capturePython = $captureCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $capturePython) { $capturePython = (Get-Command python -ErrorAction Stop).Source }
& $capturePython (Join-Path $captureRoot 'scripts/capture_viewer.py') --open-chrome

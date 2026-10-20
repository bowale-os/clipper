# Runs every automated check: backend tests with a coverage gate, frontend lint,
# frontend tests, and a production build. Stops at the first failure.
#
#   .\scripts\check.ps1            run everything
#   .\scripts\check.ps1 backend    backend tests only
#   .\scripts\check.ps1 frontend   frontend lint, tests and build only
param([ValidateSet("all", "backend", "frontend")][string]$What = "all")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Step($title) { Write-Host "`n== $title ==" -ForegroundColor Cyan }

# Run a native command and stop if it exits non-zero.
function Run {
    $command = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    & $command @rest
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code ${LASTEXITCODE}: $($args -join ' ')" }
}

if ($What -in "all", "backend") {
    Step "Backend tests (coverage gate lives in backend/.coveragerc)"
    $python = "python"
    foreach ($candidate in "$root\backend\.venv\Scripts\python.exe", "$root\backend\.venv\bin\python") {
        if (Test-Path $candidate) { $python = $candidate }
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Write-Host "note: ffmpeg not found, so the real-media tests will be skipped"
    }
    Push-Location "$root\backend"
    try { Run $python -m pytest --cov=app } finally { Pop-Location }
}

if ($What -in "all", "frontend") {
    Push-Location "$root\frontend\clippper"
    try {
        if (-not (Test-Path node_modules)) { Step "Installing frontend dependencies"; Run npm ci }
        Step "Frontend lint";  Run npm run lint
        Step "Frontend tests"; Run npm run test:coverage
        Step "Frontend build"
        if (-not $env:VITE_API_URL) { $env:VITE_API_URL = "http://localhost:8000" }
        if (-not $env:VITE_CLERK_PUBLISHABLE_KEY) { $env:VITE_CLERK_PUBLISHABLE_KEY = "pk_test_placeholder" }
        Run npm run build
    } finally { Pop-Location }
}

Write-Host "`nAll checks passed." -ForegroundColor Green

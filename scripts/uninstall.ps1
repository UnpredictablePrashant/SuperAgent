$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

$VenvRoot = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$VenvScripts = Join-Path $VenvRoot 'Scripts'

if (Test-Path $VenvPython) {
    Write-Host '[uninstall] uninstalling kendr-runtime from .venv'
    & $VenvPython -m pip show kendr-runtime *> $null
    if ($LASTEXITCODE -eq 0) {
        & $VenvPython -m pip uninstall -y kendr-runtime *> $null
    } else {
        Write-Host '[uninstall] kendr-runtime is not installed in .venv; skipping package uninstall'
    }
} else {
    Write-Host '[uninstall] .venv not found; skipping package uninstall'
}

$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ([string]::IsNullOrWhiteSpace($UserPath)) {
    $UserPath = ''
}

$PathParts = $UserPath -split ';' | Where-Object { $_ -ne '' }
$FilteredParts = $PathParts | Where-Object { $_ -ne $VenvScripts }

if ($FilteredParts.Count -ne $PathParts.Count) {
    [Environment]::SetEnvironmentVariable('Path', ($FilteredParts -join ';'), 'User')
    Write-Host "[uninstall] removed $VenvScripts from User PATH"
} else {
    Write-Host '[uninstall] no User PATH entry found for .venv\Scripts'
}

if (Test-Path $VenvRoot) {
    Remove-Item -Recurse -Force $VenvRoot
    Write-Host '[uninstall] removed .venv'
} else {
    Write-Host '[uninstall] .venv already removed'
}

Write-Host '[uninstall] done'
Write-Host '[uninstall] open a new terminal to refresh PATH'

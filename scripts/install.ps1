$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function New-LocalVenv {
    if (Test-Command -Name 'py') {
        py -3 -m venv .venv
    } else {
        python -m venv .venv
    }
}

if (-not (Test-Command -Name 'py') -and -not (Test-Command -Name 'python')) {
    throw 'Python is required but was not found in PATH.'
}

if (-not (Test-Path '.venv')) {
    Write-Host '[install] creating .venv'
    New-LocalVenv
}

$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$VenvScripts = Join-Path $RepoRoot '.venv\Scripts'

if (-not (Test-Path $VenvPython)) {
    Write-Host '[install] existing .venv is not a Windows venv; recreating .venv'
    Remove-Item -Recurse -Force .venv
    New-LocalVenv
}

Write-Host '[install] upgrading pip'
& $VenvPython -m pip install --upgrade pip

Write-Host '[install] installing package'
& $VenvPython -m pip install -e .

$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ([string]::IsNullOrWhiteSpace($UserPath)) {
    $UserPath = ''
}

$PathParts = $UserPath -split ';' | Where-Object { $_ -ne '' }
if ($PathParts -notcontains $VenvScripts) {
    $NewPath = ($PathParts + $VenvScripts) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
    Write-Host "[install] added $VenvScripts to User PATH"
} else {
    Write-Host '[install] PATH already configured'
}

if (($env:Path -split ';') -notcontains $VenvScripts) {
    $env:Path = "$VenvScripts;$env:Path"
}

Write-Host '[install] done'
Write-Host '[install] open a new terminal, then verify: superagent --help'

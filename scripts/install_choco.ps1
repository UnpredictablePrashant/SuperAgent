$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command -Name 'choco')) {
    throw 'Chocolatey (choco) is required. Install it first from https://chocolatey.org/install and rerun this script.'
}

if (-not (Test-Command -Name 'py') -and -not (Test-Command -Name 'python')) {
    Write-Host '[choco] installing python'
    choco install python -y
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

Write-Host '[choco] running SuperAgent installer'
powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot 'scripts\install.ps1')


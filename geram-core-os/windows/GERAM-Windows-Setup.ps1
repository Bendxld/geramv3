[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$')]
    [string]$Distro = 'Ubuntu-24.04'
)

$ErrorActionPreference = 'Stop'

function Invoke-WslChecked {
    param([string[]]$Arguments)
    & wsl.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'A WSL2 command failed.' }
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL2 is not installed. Open an Administrator PowerShell and run: wsl --install -d Ubuntu-24.04'
}

$installed = @(& wsl.exe --list --quiet | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($installed -notcontains $Distro) {
    Write-Host "Installing WSL distribution $Distro. Windows may request elevation or a restart."
    & wsl.exe --install -d $Distro
    if ($LASTEXITCODE -ne 0) { throw 'The WSL distribution could not be installed.' }
}

Write-Host 'Installing the Linux security/runtime dependencies inside WSL2...'
Invoke-WslChecked @(
    '-d', $Distro, '--', 'bash', '-lc',
    'set -eu; sudo apt-get update; sudo apt-get install -y python3 python3-venv bubblewrap poppler-utils git nodejs'
)

Write-Host 'Validating WSL2 and Bubblewrap...'
Invoke-WslChecked @('-d', $Distro, '--', 'bash', '-lc', 'set -eu; python3 --version; bwrap --version; node --version; git --version')

[Environment]::SetEnvironmentVariable('GERAM_WSL_DISTRO', $Distro, 'User')
Write-Host 'GERAM Windows support is ready. Start GERAM CORE OS from the Start menu.'

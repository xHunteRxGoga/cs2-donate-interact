$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $here

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    $root = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path -LiteralPath $root) {
        $found = Get-ChildItem -LiteralPath $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }
    foreach ($ver in @("Python314", "Python313", "Python312", "Python311", "Python310")) {
        $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\$ver\python.exe"
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

try {
    Unblock-File -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue
} catch {}

if (-not (Test-Admin)) {
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    Start-Process -FilePath $ps -Verb RunAs -WorkingDirectory $here -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $PSCommandPath
    )
    exit 0
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python not found. Install Python 3 and enable 'Add python.exe to PATH'."
    Write-Host "Then close this window and run run-admin.bat again."
    pause
    exit 1
}

Write-Host "Admin: yes"
Write-Host "Folder: $here"
Write-Host "Python: $python"
Write-Host "Installing dependencies..."
& $python -m pip install -r (Join-Path $here "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip failed"
    pause
    exit 1
}

Write-Host "Starting CS2 Donate Interact..."
& $python -m src.main
if ($LASTEXITCODE -ne 0) {
    pause
    exit $LASTEXITCODE
}

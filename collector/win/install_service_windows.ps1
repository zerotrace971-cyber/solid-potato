# install_service_windows.ps1
# Installs ARGUS Windows collectors as services.
# Run as Administrator: .\install_service_windows.ps1

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

$InstallDir = "C:\soc\collectors"
$LogDir     = "C:\soc\logs"
$PythonExe  = (Get-Command python.exe).Source

Write-Host "[ARGUS] Installing Windows collectors..." -ForegroundColor Cyan

# 1. Create directories
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir     | Out-Null

# 2. Copy collector files
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$files = @("collector.py", "firewall_collector.py", "risk_scoring.py")
foreach ($file in $files) {
    $source = Join-Path $ScriptDir $file
    if (Test-Path $source) {
        Copy-Item $source $InstallDir -Force
        Write-Host "[ARGUS] Copied $file" -ForegroundColor Green
    } else {
        Write-Host "[ARGUS] WARNING: $file not found in $ScriptDir" -ForegroundColor Yellow
    }
}

# 3. Install Python dependencies
Write-Host "[ARGUS] Installing Python dependencies..." -ForegroundColor Cyan
& $PythonExe -m pip install --quiet pywin32 watchdog

# 4. Download NSSM (service manager) if not present
$NssmPath = "$env:SystemRoot\System32\nssm.exe"
if (-not (Test-Path $NssmPath)) {
    Write-Host "[ARGUS] Downloading NSSM..." -ForegroundColor Cyan

    $NssmUrls = @(
        "https://nssm.cc/release/nssm-2.24.zip"
        "https://github.com/nicedayzhu/netspy/raw/master/nssm-2.24.zip"
    )
    $NssmZip = "$env:TEMP\nssm.zip"
    $NssmExtractDir = "$env:TEMP\nssm"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $downloaded = $false
    foreach ($url in $NssmUrls) {
        try {
            Write-Host "[ARGUS] Trying $url ..." -ForegroundColor Gray
            Invoke-WebRequest -Uri $url -OutFile $NssmZip -UseBasicParsing
            $downloaded = $true
            break
        } catch {
            Write-Host "[ARGUS] Failed: $_" -ForegroundColor Yellow
        }
    }
    if (-not $downloaded) {
        throw "Could not download NSSM from any mirror. Download nssm-2.24.zip manually and place nssm.exe in $NssmPath"
    }

    Expand-Archive -Path $NssmZip -DestinationPath $NssmExtractDir -Force
    $NssmExe = Get-ChildItem -Path $NssmExtractDir -Recurse -Filter "nssm.exe" |
               Where-Object { $_.DirectoryName -match "win64" } | Select-Object -First 1
    Copy-Item $NssmExe.FullName $NssmPath -Force
    Write-Host "[ARGUS] NSSM installed" -ForegroundColor Green
}

# 5. Install auth collector service
Write-Host "[ARGUS] Installing argus-auth service..." -ForegroundColor Cyan

& $NssmPath install argus-auth $PythonExe "$InstallDir\collector.py" | Out-Null
& $NssmPath set argus-auth AppDirectory $InstallDir           | Out-Null
& $NssmPath set argus-auth AppStdout "$LogDir\auth.out.log"   | Out-Null
& $NssmPath set argus-auth AppStderr "$LogDir\auth.err.log"   | Out-Null
& $NssmPath set argus-auth AppRotateFiles 1                  | Out-Null
& $NssmPath set argus-auth AppRotateBytes 10485760           | Out-Null  # 10MB
& $NssmPath set argus-auth DisplayName "ARGUS Auth Collector"     | Out-Null
& $NssmPath set argus-auth Description "Collects Windows Security/Auth events" | Out-Null
& $NssmPath set argus-auth Start SERVICE_AUTO_START           | Out-Null

# 6. Install system collector service
Write-Host "[ARGUS] Installing argus-system service..." -ForegroundColor Cyan

& $NssmPath install argus-system $PythonExe "$InstallDir\firewall_collector.py" | Out-Null
& $NssmPath set argus-system AppDirectory $InstallDir        | Out-Null
& $NssmPath set argus-system AppStdout "$LogDir\system.out.log" | Out-Null
& $NssmPath set argus-system AppStderr "$LogDir\system.err.log" | Out-Null
& $NssmPath set argus-system AppRotateFiles 1                | Out-Null
& $NssmPath set argus-system AppRotateBytes 10485760         | Out-Null
& $NssmPath set argus-system DisplayName "ARGUS System Collector"  | Out-Null
& $NssmPath set argus-system Description "Collects Windows System/Sysmon events" | Out-Null
& $NssmPath set argus-system Start SERVICE_AUTO_START        | Out-Null

# 7. Configure recovery: restart on failure
& $NssmPath set argus-auth   AppExit Default Restart          | Out-Null
& $NssmPath set argus-auth   AppRestartDelay 5000             | Out-Null
& $NssmPath set argus-system AppExit Default Restart          | Out-Null
& $NssmPath set argus-system AppRestartDelay 5000             | Out-Null

# 8. Start services
Start-Service argus-auth
Start-Service argus-system

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "[ARGUS] ========================================" -ForegroundColor Green
Write-Host "[ARGUS] Installation complete!" -ForegroundColor Green
Write-Host "[ARGUS] ========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Service status:"
Get-Service argus-auth   | Format-Table -AutoSize
Get-Service argus-system | Format-Table -AutoSize
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  Get-Service argus-auth"
Write-Host "  Get-Service argus-system"
Write-Host "  Restart-Service argus-auth"
Write-Host "  Get-Content '$LogDir\auth.out.log' -Wait"
Write-Host "  Get-Content '$LogDir\system.out.log' -Wait"
Write-Host ""
Write-Host "Uninstall:" -ForegroundColor Yellow
Write-Host "  & nssm.exe remove argus-auth confirm"
Write-Host "  & nssm.exe remove argus-system confirm"

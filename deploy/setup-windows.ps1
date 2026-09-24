# Полная установка MG Group CRM на Windows Server.
# Запуск от администратора:
#   irm https://raw.githubusercontent.com/romankutuzovdev/mg-group-bot/main/deploy/setup-windows.ps1 | iex
# или локально после clone:
#   powershell -ExecutionPolicy Bypass -File .\deploy\setup-windows.ps1
#
# Параметры (опционально):
#   -RepoUrl "https://github.com/romankutuzovdev/mg-group-bot.git"
#   -AppDir  "C:\mg-crm"
#   -TelegramToken "123:ABC"
#   -SkipService   # не ставить Windows-службу

param(
  [string]$RepoUrl = "https://github.com/romankutuzovdev/mg-group-bot.git",
  [string]$AppDir = "C:\mg-crm",
  [string]$TelegramToken = "",
  [string]$ServiceName = "mg-crm",
  [switch]$SkipService
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step([string]$Msg) {
  Write-Host ""
  Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Assert-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Запустите PowerShell от имени администратора."
  }
}

function Assert-Command([string]$Name, [string]$Hint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Не найдено: $Name. $Hint"
  }
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
  $lines = @()
  if (Test-Path $Path) {
    $lines = Get-Content $Path
  }
  $found = $false
  $out = foreach ($line in $lines) {
    if ($line -match "^\s*$([regex]::Escape($Key))\s*=") {
      $found = $true
      "$Key=$Value"
    } else {
      $line
    }
  }
  if (-not $found) {
    $out = @($out) + "$Key=$Value"
  }
  $out | Set-Content -Path $Path -Encoding UTF8
}

function Install-Nssm([string]$DestDir) {
  $nssmExe = Join-Path $DestDir "nssm.exe"
  if (Test-Path $nssmExe) { return $nssmExe }
  if (Get-Command nssm -ErrorAction SilentlyContinue) {
    return (Get-Command nssm).Source
  }

  Write-Step "Скачиваю NSSM"
  $zip = Join-Path $env:TEMP "nssm-2.24.zip"
  $extract = Join-Path $env:TEMP "nssm-extract"
  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip -UseBasicParsing
  if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
  Expand-Archive -Path $zip -DestinationPath $extract -Force
  $src = Get-ChildItem -Path $extract -Recurse -Filter "nssm.exe" |
    Where-Object { $_.FullName -match '\\win64\\nssm\.exe$' } |
    Select-Object -First 1
  if (-not $src) { throw "Не удалось найти nssm.exe в архиве." }
  New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
  Copy-Item $src.FullName $nssmExe -Force
  return $nssmExe
}

Assert-Admin
Write-Step "Проверка Git / Python / Node"
Assert-Command git "Установите Git: https://git-scm.com/download/win"
Assert-Command python "Установите Python 3.11+: https://www.python.org/downloads/ (Add to PATH)"
Assert-Command npm "Установите Node.js 20+: https://nodejs.org/"
Assert-Command node "Установите Node.js 20+: https://nodejs.org/"

$pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Python $pyVer | Node $(node -v) | npm $(npm -v)"

Write-Step "Репозиторий → $AppDir"
if (Test-Path (Join-Path $AppDir ".git")) {
  Set-Location $AppDir
  git fetch --all --prune
  git checkout main
  git reset --hard origin/main
} elseif (Test-Path $AppDir) {
  throw "Папка $AppDir уже есть, но это не git-репозиторий. Удалите её или укажите другой -AppDir."
} else {
  New-Item -ItemType Directory -Force -Path (Split-Path $AppDir -Parent) | Out-Null
  git clone $RepoUrl $AppDir
  Set-Location $AppDir
}

$deployDir = Join-Path $AppDir "deploy"
$envExample = Join-Path $deployDir "env.example"
$envFile = Join-Path $AppDir ".env"

Write-Step ".env"
if (-not (Test-Path $envFile)) {
  if (Test-Path $envExample) {
    Copy-Item $envExample $envFile
  } else {
    @"
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
POLL_INTERVAL_MINUTES=30
MAX_PAGES=0
HEADLESS=false
CHROME_HEADLESS_CDP=0
CRM_PORT=8080
CRM_HOST=0.0.0.0
"@ | Set-Content -Path $envFile -Encoding UTF8
  }
}

# Windows defaults for local Chrome / VPN
Set-EnvValue $envFile "CRM_HOST" "0.0.0.0"
Set-EnvValue $envFile "CRM_PORT" "8080"
if (-not ((Get-Content $envFile -Raw) -match '(?m)^HEADLESS=')) {
  Set-EnvValue $envFile "HEADLESS" "false"
}
if (-not ((Get-Content $envFile -Raw) -match '(?m)^CHROME_HEADLESS_CDP=')) {
  Set-EnvValue $envFile "CHROME_HEADLESS_CDP" "0"
}
if ($TelegramToken) {
  Set-EnvValue $envFile "TELEGRAM_BOT_TOKEN" $TelegramToken
}

$tokenEmpty = $true
foreach ($line in Get-Content $envFile) {
  if ($line -match '^\s*TELEGRAM_BOT_TOKEN\s*=\s*(.+)\s*$' -and $Matches[1].Trim().Length -gt 0) {
    $tokenEmpty = $false
  }
}
if ($tokenEmpty) {
  Write-Host "TELEGRAM_BOT_TOKEN пустой. Можно указать сейчас (Enter — пропустить):" -ForegroundColor Yellow
  $entered = Read-Host "Токен бота"
  if ($entered) {
    Set-EnvValue $envFile "TELEGRAM_BOT_TOKEN" $entered.Trim()
  }
}

Write-Step "Python venv + зависимости"
$venvDir = Join-Path $AppDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"
if (-not (Test-Path $venvPython)) {
  python -m venv $venvDir
}
& $venvPip install --upgrade pip
& $venvPip install -r (Join-Path $AppDir "requirements.txt")

$pwBrowsers = Join-Path $AppDir ".pw-browsers"
New-Item -ItemType Directory -Force -Path $pwBrowsers | Out-Null
$env:PLAYWRIGHT_BROWSERS_PATH = $pwBrowsers
& $venvPython -m playwright install chromium

Write-Step "Сборка frontend"
Set-Location (Join-Path $AppDir "frontend")
if (Test-Path "package-lock.json") { npm ci } else { npm install }
npm run build
Set-Location $AppDir

New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "data") | Out-Null

if (-not $SkipService) {
  $nssmExe = Install-Nssm $deployDir
  Write-Step "Служба Windows: $ServiceName"
  $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if ($existing) {
    & $nssmExe stop $ServiceName 2>$null
    Start-Sleep -Seconds 1
    & $nssmExe remove $ServiceName confirm
  }
  & $nssmExe install $ServiceName $venvPython (Join-Path $AppDir "app.py")
  & $nssmExe set $ServiceName AppDirectory $AppDir
  & $nssmExe set $ServiceName AppEnvironmentExtra "PLAYWRIGHT_BROWSERS_PATH=$pwBrowsers"
  & $nssmExe set $ServiceName Start SERVICE_AUTO_START
  & $nssmExe set $ServiceName AppStdout (Join-Path $AppDir "data\service-out.log")
  & $nssmExe set $ServiceName AppStderr (Join-Path $AppDir "data\service-err.log")
  & $nssmExe set $ServiceName AppRotateFiles 1
  Start-Service $ServiceName
  Start-Sleep -Seconds 2
  Get-Service $ServiceName | Format-List Name, Status, StartType
} else {
  Write-Host "Служба пропущена (-SkipService). Запуск вручную:"
  Write-Host "  $venvPython $(Join-Path $AppDir 'app.py')"
}

# Firewall rule for CRM port
try {
  $port = 8080
  $line = (Get-Content $envFile | Where-Object { $_ -match '^\s*CRM_PORT\s*=' } | Select-Object -First 1)
  if ($line -match '=\s*(\d+)') { $port = [int]$Matches[1] }
  $ruleName = "MG CRM $port"
  if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    Write-Step "Firewall: TCP $port"
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
  }
} catch {
  Write-Host "Firewall-правило не создано (нужны права / модуль NetSecurity): $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Готово."
Write-Host " Каталог:  $AppDir"
Write-Host " Локально: http://127.0.0.1:8080"
Write-Host " В сети:   http://$((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1).IPAddress):8080"
Write-Host " Логи:     $AppDir\data\service-out.log / service-err.log"
Write-Host " Обновить: powershell -ExecutionPolicy Bypass -File $AppDir\deploy\update-from-git.ps1"
Write-Host "============================================" -ForegroundColor Green

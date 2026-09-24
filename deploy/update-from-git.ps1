# Обновление CRM на Windows Server из GitHub (CI или вручную).
# Пример: powershell -ExecutionPolicy Bypass -File C:\mg-crm\deploy\update-from-git.ps1
$ErrorActionPreference = "Stop"

$AppDir = if ($env:APP_DIR) { $env:APP_DIR } else { "C:\mg-crm" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "main" }
$ServiceName = if ($env:SERVICE_NAME) { $env:SERVICE_NAME } else { "mg-crm" }

Set-Location $AppDir

Write-Host "==> git fetch/pull ($Branch)"
git fetch --all --prune
git checkout $Branch
git reset --hard "origin/$Branch"

Write-Host "==> Python deps"
$venvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
$venvPip = Join-Path $AppDir ".venv\Scripts\pip.exe"
if (-not (Test-Path $venvPython)) {
  python -m venv (Join-Path $AppDir ".venv")
}
& $venvPip install -q --upgrade pip
& $venvPip install -q -r (Join-Path $AppDir "requirements.txt")

Write-Host "==> Frontend build"
Set-Location (Join-Path $AppDir "frontend")
if (Test-Path "package-lock.json") {
  npm ci
} else {
  npm install
}
npm run build
Set-Location $AppDir

# .env на сервере не трогаем
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "data") | Out-Null

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
  Write-Host "==> restart $ServiceName"
  Restart-Service -Name $ServiceName -Force
  Start-Sleep -Seconds 2
  Get-Service -Name $ServiceName | Format-List Name, Status, StartType
} else {
  Write-Host "==> служба $ServiceName не найдена — перезапустите app.py вручную"
}

Write-Host "Готово."

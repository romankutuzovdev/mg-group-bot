# Публичная ссылка на CRM. Пока этот процесс запущен — ссылка жива.
# При каждом новом запуске Cloudflare выдаёт другой адрес.
$cf = Join-Path $PSScriptRoot "tools\cloudflared.exe"
if (-not (Test-Path $cf)) {
    Write-Error "Нет tools\cloudflared.exe. Скачайте cloudflared-windows-amd64.exe в папку tools."
    exit 1
}
& $cf tunnel --url http://127.0.0.1:8080 --no-autoupdate

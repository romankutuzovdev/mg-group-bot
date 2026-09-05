# Постоянный туннель ngrok на CRM (порт 8080).
# Токен и домен берутся из .env: NGROK_AUTHTOKEN, NGROK_DOMAIN
$root = $PSScriptRoot
$ngrok = Join-Path $root "tools\ngrok.exe"
$envFile = Join-Path $root ".env"

if (-not (Test-Path $ngrok)) {
    Write-Error "Нет tools\ngrok.exe"
    exit 1
}
if (-not (Test-Path $envFile)) {
    Write-Error "Нет файла .env"
    exit 1
}

Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#" -or $_ -notmatch "=") { return }
    $k, $v = $_.Split("=", 2)
    Set-Item -Path "Env:$($k.Trim())" -Value $v.Trim()
}

if (-not $env:NGROK_AUTHTOKEN) {
    Write-Error "Заполните NGROK_AUTHTOKEN в .env"
    exit 1
}

& $ngrok config add-authtoken $env:NGROK_AUTHTOKEN | Out-Null

if ($env:NGROK_DOMAIN) {
    $url = $env:NGROK_DOMAIN
    if ($url -notmatch "^https?://") { $url = "https://$url" }
    & $ngrok http --url=$url 8080
} else {
    & $ngrok http 8080
}

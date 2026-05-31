# transfer-to-vps.ps1 — kirim source + file deploy ke VPS untuk deploy manual (build di VPS).
# Jalankan dari ROOT project (d:\sadam\Dev\Projects\aitf) di PowerShell:
#   .\aitf-backend\deploy\transfer-to-vps.ps1
# Prasyarat: OpenSSH client (scp/ssh) aktif di Windows; jaringan/VPN ITS tersambung.

$ErrorActionPreference = "Stop"
$VPS  = "user@10.199.13.176"
$ROOT = (Resolve-Path "$PSScriptRoot\..\..").Path   # -> d:\sadam\Dev\Projects\aitf
Set-Location $ROOT

$bundle = Join-Path $env:TEMP "aitf-src.tgz"
Write-Host ">> Membuat bundle source (tanpa node_modules/.venv/.next/.git/cache/log) ..."
# tar.exe bawaan Windows 10/11 (bsdtar)
tar --exclude=node_modules --exclude=.venv --exclude=.next --exclude=.git `
    --exclude=.mypy_cache --exclude=.pytest_cache --exclude=.ruff_cache `
    --exclude=__pycache__ --exclude="*.log" --exclude=.cache `
    -czf "$bundle" aitf-backend aitf-frontend

Write-Host ">> Mengirim bundle + file deploy ke $VPS ..."
scp "$bundle" "$VPS`:~/aitf-src.tgz"
scp "aitf-backend\deploy\docker-compose.build.yml" `
    "aitf-backend\deploy\deploy-build.sh" `
    "aitf-backend\deploy\bootstrap_vps.sh" `
    "aitf-backend\deploy\.env.prod.example" `
    "$VPS`:~/"

Write-Host ""
Write-Host ">> SELESAI transfer. Sekarang SSH ke VPS dan jalankan:" -ForegroundColor Green
Write-Host @"
  ssh $VPS
  # (sekali) install docker + firewall, lalu login ulang:
  bash ~/bootstrap_vps.sh && exit
  ssh $VPS
  mkdir -p ~/aitf && tar -xzf ~/aitf-src.tgz -C ~/aitf
  mv ~/docker-compose.build.yml ~/deploy-build.sh ~/.env.prod.example ~/aitf/
  cd ~/aitf && cp .env.prod.example .env && nano .env   # isi semua secret
  bash deploy-build.sh
"@

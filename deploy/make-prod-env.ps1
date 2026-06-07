# make-prod-env.ps1 - buat .env PRODUKSI dari aitf-backend\.env lokal (secret ikut terisi),
# simpan ke %TEMP%\aitf-prod.env. Host/port publik diatur via parameter.
# Contoh:  .\aitf-backend\deploy\make-prod-env.ps1 -PublicHost 194.233.95.22 -FePort 3001
param(
  [string]$PublicHost = "194.233.95.22",
  [int]$ApiPort = 8000,
  [int]$FePort = 3001
)
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "..\.env"   # -> aitf-backend\.env
if (-not (Test-Path $src)) { throw "Tidak ketemu $src - pastikan .env dev Anda ada." }

$kv = @{}
Get-Content $src | ForEach-Object {
  if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $kv[$matches[1]] = $matches[2].Trim() }
}
function V([string]$k, [string]$def = "") { if ($kv.ContainsKey($k) -and $kv[$k]) { return $kv[$k] } return $def }

$lines = @(
 "APP_ENV=production","PAD_ENVIRONMENT=prod","PAD_HOST=0.0.0.0","PAD_PORT=8000","PAD_RELOAD=false","PAD_LOG_LEVEL=INFO","PAD_WORKERS_COUNT=1",
 "PAD_POSTGRES_HOST=pad-postgres","PAD_POSTGRES_PORT=5432","PAD_POSTGRES_USER=$(V 'PAD_POSTGRES_USER' 'pad')","PAD_POSTGRES_PASS=$(V 'PAD_POSTGRES_PASS' 'pad')","PAD_POSTGRES_DB=$(V 'PAD_POSTGRES_DB' 'pad')",
 "PAD_MONGO_HOST=pad-mongo","PAD_MONGO_PORT=27017","PAD_MONGO_USER=$(V 'PAD_MONGO_USER' 'pad')","PAD_MONGO_PASS=$(V 'PAD_MONGO_PASS' 'pad')","PAD_MONGO_DB=$(V 'PAD_MONGO_DB' 'pad')",
 "PAD_MINIO_HOST=pad-minio","PAD_MINIO_PORT=9000","PAD_MINIO_ACCESS_KEY=$(V 'PAD_MINIO_ACCESS_KEY' 'minioadmin')","PAD_MINIO_SECRET_KEY=$(V 'PAD_MINIO_SECRET_KEY' 'minioadmin')","PAD_MINIO_BUCKET=$(V 'PAD_MINIO_BUCKET' 'pad-bucket')","PAD_MINIO_USE_SSL=false",
 "QDRANT_URL=$(V 'QDRANT_URL')","QDRANT_API_KEY=$(V 'QDRANT_API_KEY')","QDRANT_COLLECTION_DEV=$(V 'QDRANT_COLLECTION_DEV' 'pad_hukum_dev')","QDRANT_COLLECTION_PROD=$(V 'QDRANT_COLLECTION_PROD' 'pad_hukum_prod')","SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers",
 "OPENROUTER_API_KEY=$(V 'OPENROUTER_API_KEY')",
 "APIFY_API_FREE=$(V 'APIFY_API_FREE')","APIFY_API_PREMIUM=$(V 'APIFY_API_PREMIUM')",
 "IG_USER=$(V 'IG_USER')","IG_PASS=$(V 'IG_PASS')","TW_USER=$(V 'TW_USER')","TW_PASS=$(V 'TW_PASS')",
 "FRONTEND_HOST_PORT=$FePort",
 "PUBLIC_API_URL=http://${PublicHost}:${ApiPort}/api",
 "SITE_URL=http://${PublicHost}:${FePort}"
)
$txt = ($lines -join "`n") + "`n"
$dst = Join-Path $env:TEMP "aitf-prod.env"
[System.IO.File]::WriteAllText($dst, $txt, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host "OK -> $dst" -ForegroundColor Green
Write-Host ("API URL di-bake: http://{0}:{1}/api   | frontend host port: {2}" -f $PublicHost, $ApiPort, $FePort)

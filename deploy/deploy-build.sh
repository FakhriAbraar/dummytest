#!/usr/bin/env bash
# deploy-build.sh — build image dari source & jalankan, di VPS. TANPA GitHub/GHCR.
#   cd ~/aitf && bash deploy-build.sh
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.build.yml --env-file .env"

if [ ! -f .env ]; then
  echo "ERROR: .env belum ada. Jalankan: cp .env.prod.example .env && nano .env"; exit 1
fi
if [ ! -d aitf-backend ] || [ ! -d aitf-frontend ]; then
  echo "ERROR: folder aitf-backend/ dan aitf-frontend/ harus ada di sini (hasil transfer source)."; exit 1
fi

echo ">> build + up (build pertama LAMA: torch + playwright + llama, butuh disk >=20GB) ..."
# TANPA --remove-orphans: di server bersama, jangan sampai menyentuh container lain.
$COMPOSE up -d --build

echo ">> tunggu DB & migrasi ..."
sleep 12

echo ">> seed referensi (IGRS dll) — sekali ..."
$COMPOSE exec -T api python -m app.seeds.main_seed || echo "(seed dilewati / sudah ada)"

echo ">> health check ..."
if curl -fsS http://localhost:8000/api/docs >/dev/null; then echo "OK: backend up"; else echo "WARN: backend belum siap → $COMPOSE logs -f api"; fi

echo ">> status:"
$COMPOSE ps
echo ">> Frontend: http://<IP-VPS>:3000   |   API docs: http://<IP-VPS>:8000/api/docs"

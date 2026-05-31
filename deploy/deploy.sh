#!/usr/bin/env bash
# deploy.sh — deploy MANUAL di VPS (first run / emergency).
# CI/CD GitHub Actions sudah otomatis; script ini untuk setup pertama.
#   cd ~/aitf
#   GHCR_USER=<github-user> GHCR_TOKEN=<PAT read:packages> bash deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"

if [ ! -f .env ]; then
  echo "ERROR: .env tidak ada. Jalankan: cp .env.prod.example .env && nano .env"
  exit 1
fi

if [ -n "${GHCR_USER:-}" ] && [ -n "${GHCR_TOKEN:-}" ]; then
  echo ">> login GHCR ..."
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
fi

echo ">> pull images ..."
$COMPOSE pull

echo ">> up -d ..."
$COMPOSE up -d --remove-orphans

echo ">> tunggu DB siap ..."
sleep 10

# `alembic upgrade head` sudah jalan otomatis lewat command service `api`.
echo ">> seed referensi (IGRS, dll) — sekali saja, aman diulang bila idempotent ..."
$COMPOSE exec -T api python -m app.seeds.main_seed || echo "(seed dilewati / sudah ada)"

echo ">> health check ..."
curl -fsS http://localhost:8000/api/docs >/dev/null && echo "OK: backend up" || echo "WARN: backend belum siap, cek: $COMPOSE logs -f api"

echo ">> status:"
$COMPOSE ps

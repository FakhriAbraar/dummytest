#!/usr/bin/env bash
# bootstrap_vps.sh — install Docker + buka firewall + siapkan folder ~/aitf.
# Jalankan SEKALI di VPS (user dengan sudo):  bash bootstrap_vps.sh
set -euo pipefail

PROJECT_DIR="${HOME}/aitf"

echo ">> update apt ..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release git ufw

if ! command -v docker >/dev/null 2>&1; then
  echo ">> install Docker Engine + Compose plugin ..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
fi

echo ">> buka port firewall ..."
for p in 22 80 443 3000 8000 9001; do sudo ufw allow "${p}/tcp" || true; done
sudo ufw --force enable || true

mkdir -p "$PROJECT_DIR"
echo ">> folder siap: $PROJECT_DIR"
echo ">> SELESAI. Logout/login lagi supaya group 'docker' aktif tanpa sudo."
echo "   Lalu copy docker-compose.prod.yml, deploy.sh, .env (dari .env.prod.example) ke $PROJECT_DIR"

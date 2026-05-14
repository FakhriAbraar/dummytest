#!/bin/bash

cd /path/ke/pad-backend || exit

source .venv/bin/activate

# (FastAPI yang  eksekusi LangGraph secara Asynchronous)
echo "[$(date)] Mengirim sinyal trigger ke Agent..."

curl -X 'POST' \
  'http://localhost:8000/api/v1/trigger-crawler' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "seed_trend": "", 
  "max_depth": 3
}' >> /var/log/pad_crawler.log 2>&1

echo "[$(date)] Trigger terkirim. Proses berjalan di background."

# config crontab
# setiap 6 jam (Jam 00:00, 06:00, 12:00, 18:00)
# 0 */6 * * * /bin/bash /path/ke/pad-backend/run_crawler.sh
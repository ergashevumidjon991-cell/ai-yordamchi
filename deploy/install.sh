#!/usr/bin/env bash
# Ubuntu 24.04 serverga o'rnatish. Ishga tushirish: bash deploy/install.sh
set -euo pipefail
APP=/opt/ai-yordamchi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv ffmpeg git

if [ "$(pwd)" != "$APP" ]; then
  mkdir -p "$APP"
  cp -r . "$APP"
fi
cd "$APP"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

[ -f .env ] || venv/bin/python sozlash.py

cp deploy/ai-yordamchi.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ai-yordamchi
systemctl restart ai-yordamchi
sleep 5
systemctl --no-pager status ai-yordamchi | head -5
echo ">>> Tayyor! Telegramda botingizga /start yozing."

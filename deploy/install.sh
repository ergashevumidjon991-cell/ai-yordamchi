#!/usr/bin/env bash
# Ubuntu 24.04 serverga o'rnatish. Ishga tushirish: bash deploy/install.sh
set -euo pipefail
APP=/opt/ai-yordamchi

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

[ -f .env ] || { cp .env.example .env; echo ">>> .env faylini to'ldiring: nano $APP/.env"; }

cp deploy/ai-yordamchi.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ai-yordamchi
echo ">>> Tayyor. .env to'ldirilgach: systemctl restart ai-yordamchi"

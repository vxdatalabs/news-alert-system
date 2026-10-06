#!/usr/bin/env bash
# Runs ON the Oracle VM (called by deploy.sh over ssh). Installs deps,
# verifies timezone data, installs the systemd service, and starts it.
set -euo pipefail

cd "$HOME/news_alert_app"

echo "--- installing python deps ---"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-pip >/dev/null
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip >/dev/null
fi
pip3 install --user -r requirements.txt

echo "--- checking US/Eastern timezone data is available ---"
python3 -c "from zoneinfo import ZoneInfo; ZoneInfo('America/New_York'); print('tzdata OK')" \
  || { echo "tzdata missing, installing..."; sudo dnf install -y tzdata 2>/dev/null || sudo apt-get install -y tzdata; }

echo "--- installing systemd service ---"
sudo cp deploy/news-alert.service /etc/systemd/system/news-alert.service
sudo systemctl daemon-reload
sudo systemctl enable news-alert
sudo systemctl restart news-alert

sleep 2
echo "--- status ---"
sudo systemctl status news-alert --no-pager || true
echo ""
echo "Done. Tail logs with: journalctl -u news-alert -f"

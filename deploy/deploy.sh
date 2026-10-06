#!/usr/bin/env bash
# Run this FROM YOUR MAC (in Terminal), from inside news_alert_app/.
# Copies the project to your VM and runs remote setup over ssh.
#
# Usage:
#   VM_HOST=opc@YOUR.VM.IP.ADDRESS SSH_KEY=~/path/to/your-key.key ./deploy/deploy.sh
set -euo pipefail

KEY="${SSH_KEY:?Set SSH_KEY=/path/to/your-private-key.key}"
HOST="${VM_HOST:?Set VM_HOST=user@your.vm.ip.address}"

echo "--- copying project to VM ---"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" "mkdir -p ~/news_alert_app/logs"
# NOTE: .env is deliberately NOT copied here. The VM's .env holds the
# live Finnhub key + Telegram bot token/chat_id, which may have been
# rotated/changed directly on the VM since this local copy was made -
# copying a stale local .env over would silently break delivery. Edit
# .env directly on the VM (ssh in, nano .env) if it ever needs changing.
scp -i "$KEY" -o StrictHostKeyChecking=accept-new \
  config.py news_provider.py telegram_notifier.py discord_notifier.py news_loop.py \
  get_telegram_chat_id.py requirements.txt \
  "$HOST:~/news_alert_app/"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new -r deploy "$HOST:~/news_alert_app/"

echo "--- running remote setup ---"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST" "bash ~/news_alert_app/deploy/remote_setup.sh"

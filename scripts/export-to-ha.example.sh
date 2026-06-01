#!/bin/zsh
set -euo pipefail

REPO="${CODEX_USAGE_REPO:-$HOME/Documents/codex/codex-usage}"
PYTHON="${PYTHON:-/usr/bin/python3}"
OUT="${CODEX_USAGE_OUT:-$HOME/.codex/ha-codex-usage-summary.json}"
SSH_KEY="${HA_SSH_KEY:?Set HA_SSH_KEY to your Home Assistant SSH private key}"
HA_HOST="${HA_HOST:?Set HA_HOST to your Home Assistant host or IP}"
HA_PORT="${HA_PORT:-2222}"
HA_TARGET="${HA_TARGET:-/config/www/codex-usage/summary.json}"

"$PYTHON" "$REPO/ha_export.py" --output "$OUT"
ssh -i "$SSH_KEY" -p "$HA_PORT" "root@$HA_HOST" "mkdir -p /config/www/codex-usage"
scp -q -i "$SSH_KEY" -P "$HA_PORT" "$OUT" "root@$HA_HOST:$HA_TARGET"

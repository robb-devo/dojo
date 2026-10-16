#!/usr/bin/env bash
# Dojo agent installer (idempotent). Run as root:  sudo bash install.sh [--roots /opt/minecraft:/home/mc] [--model qwen2.5:3b]
set -euo pipefail
ROOTS="/opt/minecraft:/home:/srv"; MODEL="qwen2.5:3b"; PORT=8765
while [[ $# -gt 0 ]]; do case "$1" in --roots) ROOTS="$2"; shift 2;; --model) MODEL="$2"; shift 2;; --port) PORT="$2"; shift 2;; *) echo "unknown arg $1"; exit 1;; esac; done
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 1; }
command -v python3 >/dev/null || { apt-get update -qq && apt-get install -y -qq python3; }
HERE="$(cd "$(dirname "$0")" && pwd)"
id dojo-agent &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin dojo-agent
install -d -m 755 /opt/dojo-agent
install -m 644 "$HERE/dojo_agent.py" /opt/dojo-agent/dojo_agent.py
install -d -m 750 -g dojo-agent /etc/dojo-agent
ENV=/etc/dojo-agent/agent.env
if [[ -f $ENV ]] && grep -q '^DOJO_TOKEN=' $ENV; then TOKEN=$(sed -n 's/^DOJO_TOKEN=//p' $ENV); NEW=0; else TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))'); NEW=1; fi
cat > $ENV <<EOT
DOJO_TOKEN=$TOKEN
DOJO_BIND=127.0.0.1
DOJO_PORT=$PORT
DOJO_MC_ROOTS=$ROOTS
DOJO_OLLAMA=http://127.0.0.1:11434
DOJO_MODEL=$MODEL
DOJO_ORIGINS=https://robb-devo.github.io,https://localhost,capacitor://localhost
EOT
chmod 640 $ENV; chgrp dojo-agent $ENV
install -m 644 "$HERE/dojo-agent.service" /etc/systemd/system/dojo-agent.service
systemctl daemon-reload; systemctl enable --now dojo-agent; systemctl restart dojo-agent; sleep 1
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null && echo "dojo-agent is running on 127.0.0.1:$PORT" || { echo "agent failed:"; journalctl -u dojo-agent -n 20 --no-pager; exit 1; }
echo; [[ $NEW == 1 ]] && echo "NEW TOKEN (enter it in Dojo > More > Agent):" || echo "Existing token kept:"
echo "  $TOKEN"
echo; echo "Next: expose it via HTTPS (see agent/README.md, Caddy or Cloudflare Tunnel)."

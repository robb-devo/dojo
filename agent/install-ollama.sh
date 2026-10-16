#!/usr/bin/env bash
# Installs Ollama, limited so it never starves the Minecraft servers. Run as root.  sudo bash install-ollama.sh [model]
set -euo pipefail
MODEL="${1:-qwen2.5:3b}"
[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/dojo-limits.conf <<'EOT'
[Service]
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_KEEP_ALIVE=5m
Environment=OLLAMA_NUM_THREADS=4
# 4 cores max, lowest priority for CPU and disk, hard RAM cap
CPUQuota=400%
Nice=19
CPUSchedulingPolicy=batch
IOSchedulingClass=idle
MemoryMax=8G
MemorySwapMax=0
EOT
systemctl daemon-reload; systemctl enable ollama; systemctl restart ollama; sleep 3
ollama pull "$MODEL"
echo "Quick speed test:"; time (curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"Say osu in 5 words\",\"stream\":false,\"options\":{\"num_thread\":4}}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["response"])')
echo "If replies take >15s, stay on a 3b model. To try 7b: sudo bash install-ollama.sh qwen2.5:7b and set DOJO_MODEL in /etc/dojo-agent/agent.env"

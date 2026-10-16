# dojo-agent

Read-only JSON API that feeds the Dojo app with live server data. Python 3 stdlib only (no pip), ~20 MB RAM.

## Endpoints (all except /api/health need `Authorization: Bearer <token>`)
| GET /api/health | liveness |
|---|---|
| GET /api/system | OS, kernel, CPU model + per-core %, RAM, swap, disks, load, uptime, network, Java versions |
| GET /api/minecraft | discovered servers (running java processes + config dirs under `DOJO_MC_ROOTS`): type (Paper/Velocity/...), version, port, role, plugins + versions, local ping player counts, velocity backends |
| GET /api/overview | everything above + AI status |
| GET /api/logs?server=<id>&lines=150 | tail of logs/latest.log, IPs and secrets masked |
| POST /api/chat `{messages:[...]}` | proxy to local Ollama (model fixed by `DOJO_MODEL`) |

Nothing writes to the server; no RCON yet. It runs as user `dojo-agent` with only CAP_DAC_READ_SEARCH (read files) and CAP_SYS_PTRACE (see other users' process dirs).

## Install (on the server, as root)
```bash
git clone https://github.com/robb-devo/dojo.git /opt/dojo-src   # or: cd /opt/dojo-src && git pull
cd /opt/dojo-src/agent
sudo bash install-ollama.sh qwen2.5:3b          # optional, for the AI sensei
sudo bash install.sh --roots /path/to/minecraft  # prints the token
```
Re-running is safe; the token is kept. New token: delete `/etc/dojo-agent/agent.env` and re-run.

## Expose via HTTPS (pick one; the agent only listens on 127.0.0.1)
**Caddy** (auto Let's Encrypt): add DNS A record `dojo.donnernet.de -> <server IP>`, open 80/443, then
```bash
sudo apt install -y caddy
echo 'dojo.donnernet.de {
  reverse_proxy 127.0.0.1:8765
}' | sudo tee /etc/caddy/Caddyfile && sudo systemctl reload caddy
```
**Cloudflare Tunnel** (no open ports; domain must be on Cloudflare):
```bash
cloudflared tunnel login && cloudflared tunnel create dojo
cloudflared tunnel route dns dojo dojo.donnernet.de
# ~/.cloudflared/config.yml: tunnel: <id> / credentials-file: ... / ingress: - hostname: dojo.donnernet.de  service: http://127.0.0.1:8765  - service: http_status:404
sudo cloudflared service install
```
Then in Dojo: More → Agent → URL `https://dojo.donnernet.de`, paste the token → Test.

Uninstall: `systemctl disable --now dojo-agent; rm -rf /opt/dojo-agent /etc/dojo-agent /etc/systemd/system/dojo-agent.service; userdel dojo-agent`

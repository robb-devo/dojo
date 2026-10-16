#!/usr/bin/env python3
"""dojo-agent: tiny read-only JSON API for the Dojo app. Python 3.8+ stdlib only."""
import hmac, http.server, json, os, re, socket, socketserver, ssl, struct, subprocess, time, zipfile, glob, platform, urllib.request
from urllib.parse import urlparse, parse_qs

VERSION = "1.0.0"
CFG = {
    "token": os.environ.get("DOJO_TOKEN", ""),
    "bind": os.environ.get("DOJO_BIND", "127.0.0.1"),
    "port": int(os.environ.get("DOJO_PORT", "8765")),
    "roots": [p for p in os.environ.get("DOJO_MC_ROOTS", "/opt/minecraft:/home:/srv:/var/opt/minecraft").split(":") if p],
    "ollama": os.environ.get("DOJO_OLLAMA", "http://127.0.0.1:11434"),
    "model": os.environ.get("DOJO_MODEL", "qwen2.5:3b"),
    "origins": [o for o in os.environ.get("DOJO_ORIGINS", "https://robb-devo.github.io,https://localhost,capacitor://localhost,http://localhost").split(",") if o],
    "cert": os.environ.get("DOJO_TLS_CERT", ""), "key": os.environ.get("DOJO_TLS_KEY", ""),
}

def rd(p, d=""):
    try:
        with open(p, errors="replace") as f: return f.read()
    except Exception: return d

# ---------------- system ----------------
def cpu_times():
    out = {}
    for l in rd("/proc/stat").splitlines():
        if l.startswith("cpu"):
            p = l.split(); v = list(map(int, p[1:]))
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            out[p[0]] = (sum(v), idle)
    return out

def java_versions():
    res, seen = [], set()
    cands = glob.glob("/usr/lib/jvm/*/bin/java") + glob.glob("/opt/*/bin/java") + glob.glob("/opt/java/*/bin/java")
    for c in ["java"] + cands:
        try:
            real = os.path.realpath(c if "/" in c else (subprocess.run(["which", c], capture_output=True, text=True).stdout.strip() or c))
            if real in seen: continue
            seen.add(real)
            r = subprocess.run([real, "-version"], capture_output=True, text=True, timeout=5)
            line = (r.stderr or r.stdout).splitlines()[0] if (r.stderr or r.stdout) else ""
            res.append({"path": real, "version": line, "default": c == "java"})
        except Exception: pass
    return res

def system_info():
    t1 = cpu_times(); time.sleep(0.25); t2 = cpu_times()
    usage = {}
    for k in t2:
        dt = t2[k][0] - t1.get(k, (0, 0))[0]; di = t2[k][1] - t1.get(k, (0, 0))[1]
        usage[k] = round(100 * (1 - di / dt), 1) if dt else 0.0
    mem = {}
    for l in rd("/proc/meminfo").splitlines():
        k, _, v = l.partition(":"); mem[k] = int(v.split()[0]) * 1024 if v.split() else 0
    model = next((l.split(":", 1)[1].strip() for l in rd("/proc/cpuinfo").splitlines() if l.startswith("model name")), platform.processor())
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', rd("/etc/os-release"), re.M))
    disks, seen = [], set()
    for l in rd("/proc/mounts").splitlines():
        dev, mnt, fs = l.split()[:3]
        if fs in ("ext4", "xfs", "btrfs", "zfs", "ext3", "f2fs", "vfat") and dev not in seen:
            seen.add(dev)
            try:
                s = os.statvfs(mnt); tot = s.f_blocks * s.f_frsize; free = s.f_bavail * s.f_frsize
                disks.append({"mount": mnt, "device": dev, "fs": fs, "total": tot, "used": tot - free, "free": free})
            except Exception: pass
    net = []
    for l in rd("/proc/net/dev").splitlines()[2:]:
        n, _, v = l.partition(":"); v = v.split(); n = n.strip()
        if n != "lo" and v: net.append({"iface": n, "rx": int(v[0]), "tx": int(v[8])})
    la = rd("/proc/loadavg").split()[:3]
    return {
        "hostname": socket.gethostname(), "os": osr.get("PRETTY_NAME", platform.system()), "kernel": platform.release(),
        "arch": platform.machine(), "uptime": int(float(rd("/proc/uptime", "0").split()[0])),
        "cpu": {"model": model, "cores": os.cpu_count(), "total": usage.pop("cpu", 0),
                "perCore": [usage[k] for k in sorted(usage, key=lambda x: int(x[3:]))]},
        "load": [float(x) for x in la] if la else [],
        "memory": {"total": mem.get("MemTotal", 0), "available": mem.get("MemAvailable", 0), "used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)},
        "swap": {"total": mem.get("SwapTotal", 0), "used": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)},
        "disks": disks, "network": net, "java": java_versions(),
    }

# ---------------- minecraft ----------------
def slp(port, host="127.0.0.1", timeout=2.0):
    """Minecraft Server List Ping (works for Paper/Spigot/Velocity/Bungee)."""
    def varint(n):
        b = b""
        while True:
            x = n & 0x7F; n >>= 7
            b += struct.pack("B", x | (0x80 if n else 0))
            if not n: return b
    def rvar(s):
        n = 0
        for i in range(5):
            c = s.recv(1)
            if not c: raise IOError("eof")
            n |= (c[0] & 0x7F) << (7 * i)
            if not c[0] & 0x80: return n
        raise IOError("varint")
    try:
        with socket.create_connection((host, port), timeout) as s:
            h = host.encode()
            d = varint(0) + varint(767) + varint(len(h)) + h + struct.pack(">H", port) + varint(1)
            s.sendall(varint(len(d)) + d + b"\x01\x00")
            rvar(s); rvar(s); ln = rvar(s); buf = b""
            while len(buf) < ln:
                c = s.recv(ln - len(buf))
                if not c: break
                buf += c
            j = json.loads(buf.decode("utf-8", "replace"))
            p = j.get("players", {})
            return {"online": True, "players": p.get("online", 0), "max": p.get("max", 0),
                    "sample": [x.get("name") for x in p.get("sample", []) or []], "version": j.get("version", {}).get("name")}
    except Exception as e:
        return {"online": False, "error": str(e)[:80]}

def props(path):
    out = {}
    for l in rd(path).splitlines():
        if l and not l.startswith("#") and "=" in l:
            k, _, v = l.partition("="); out[k.strip()] = v.strip()
    return out

def toml_get(text, key):
    m = re.search(r'^\s*' + re.escape(key) + r'\s*=\s*"?([^"\n#]*)"?', text, re.M)
    return m.group(1).strip() if m else None

def jar_info(path):
    name = os.path.basename(path).lower(); kind = "unknown"
    for k in ("velocity", "waterfall", "bungeecord", "purpur", "folia", "paper", "spigot", "fabric", "forge", "neoforge", "pufferfish", "leaves"):
        if k in name: kind = k; break
    ver = None
    try:
        with zipfile.ZipFile(path) as z:
            n = z.namelist()
            if "version.json" in n:
                ver = json.loads(z.read("version.json")).get("name") or ver
            mf = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace") if "META-INF/MANIFEST.MF" in n else ""
            m = re.search(r"Implementation-Version:\s*(\S+)", mf)
            if m and not ver: ver = m.group(1)
            if kind == "unknown":
                t = re.search(r"Implementation-Title:\s*(.+)", mf)
                if t: kind = t.group(1).strip().lower()
                if "com/velocitypowered/" in " ".join(n[:400]): kind = "velocity"
                elif any(x.startswith("io/papermc/") for x in n[:2000]): kind = "paper"
    except Exception: pass
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", os.path.basename(path))
    return {"jar": os.path.basename(path), "type": kind, "version": ver or (m.group(1) if m else None)}

def plugin_meta(jar):
    try:
        with zipfile.ZipFile(jar) as z:
            n = set(z.namelist())
            for f in ("paper-plugin.yml", "plugin.yml", "bungee.yml"):
                if f in n:
                    t = z.read(f).decode("utf-8", "replace")
                    g = lambda k: (re.search(r"^" + k + r":\s*['\"]?([^'\"\n]+)", t, re.M) or [None, None])[1]
                    return {"name": (g("name") or os.path.basename(jar)).strip(), "version": (g("version") or "").strip(), "file": os.path.basename(jar)}
            if "velocity-plugin.json" in n:
                j = json.loads(z.read("velocity-plugin.json"))
                return {"name": j.get("name") or j.get("id"), "version": str(j.get("version", "")), "file": os.path.basename(jar)}
    except Exception: pass
    return {"name": os.path.basename(jar), "version": "", "file": os.path.basename(jar)}

def java_procs():
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            if not cmd or not os.path.basename(cmd[0].decode()).startswith("java"): continue
            args = [c.decode("utf-8", "replace") for c in cmd if c]
            cwd = os.readlink(f"/proc/{pid}/cwd")
            st = rd(f"/proc/{pid}/status"); rss = re.search(r"VmRSS:\s+(\d+)", st)
            jar = next((args[i + 1] for i, a in enumerate(args) if a == "-jar" and i + 1 < len(args)), None)
            xmx = next((a[4:] for a in args if a.startswith("-Xmx")), None)
            out.append({"pid": int(pid), "cwd": cwd, "jar": jar, "xmx": xmx, "rss": int(rss.group(1)) * 1024 if rss else None})
        except Exception: pass
    return out

def server_dirs():
    dirs = set()
    for r in CFG["roots"]:
        for pat in ("server.properties", "velocity.toml", "config.yml"):
            for depth in ("", "*/", "*/*/", "*/*/*/"):
                for f in glob.glob(os.path.join(r, depth + pat)):
                    d = os.path.dirname(f)
                    if pat != "config.yml" or glob.glob(os.path.join(d, "*bungee*.jar")) or glob.glob(os.path.join(d, "*waterfall*.jar")):
                        dirs.add(os.path.realpath(d))
    return dirs

def minecraft():
    procs = java_procs(); dirs = server_dirs() | {p["cwd"] for p in procs}
    servers = []
    for d in sorted(dirs):
        if not (os.path.exists(os.path.join(d, "server.properties")) or os.path.exists(os.path.join(d, "velocity.toml")) or glob.glob(os.path.join(d, "*.jar"))): continue
        proc = next((p for p in procs if p["cwd"] == d), None)
        jarp = None
        if proc and proc["jar"]: jarp = proc["jar"] if os.path.isabs(proc["jar"]) else os.path.join(d, proc["jar"])
        if not jarp or not os.path.exists(jarp):
            jars = sorted(glob.glob(os.path.join(d, "*.jar")), key=os.path.getsize, reverse=True); jarp = jars[0] if jars else None
        info = jar_info(jarp) if jarp else {"jar": None, "type": "unknown", "version": None}
        port, role, extra = None, "backend", {}
        if os.path.exists(os.path.join(d, "velocity.toml")):
            t = rd(os.path.join(d, "velocity.toml")); role = "proxy"; info["type"] = "velocity" if info["type"] == "unknown" else info["type"]
            b = toml_get(t, "bind") or "0.0.0.0:25577"; port = int(b.rsplit(":", 1)[-1])
            sec = re.search(r"^\[servers\](.*?)(^\[|\Z)", t, re.M | re.S)
            extra["backends"] = dict(re.findall(r'^\s*([\w-]+)\s*=\s*"([^"]+)"', sec.group(1), re.M)) if sec else {}
            extra["backends"].pop("try", None)
        elif os.path.exists(os.path.join(d, "server.properties")):
            p = props(os.path.join(d, "server.properties")); port = int(p.get("server-port", 25565) or 25565)
            extra = {"motd": p.get("motd"), "maxPlayers": p.get("max-players"), "onlineMode": p.get("online-mode"), "level": p.get("level-name")}
        else:
            c = rd(os.path.join(d, "config.yml")); m = re.search(r"host:\s*\S*:(\d+)", c); port = int(m.group(1)) if m else 25577; role = "proxy"
        plugins = [plugin_meta(j) for j in sorted(glob.glob(os.path.join(d, "plugins", "*.jar")))]
        mods = [os.path.basename(j) for j in sorted(glob.glob(os.path.join(d, "mods", "*.jar")))]
        servers.append({"id": re.sub(r"[^\w-]", "_", d.strip("/")), "name": os.path.basename(d), "dir": d, "role": role, **info,
                        "port": port, "running": bool(proc), "process": proc, "ping": slp(port) if port else None,
                        "plugins": plugins, "mods": mods, "hasLog": os.path.exists(os.path.join(d, "logs", "latest.log")), **extra})
    return {"servers": servers, "javaProcesses": len(procs)}

IP_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b")
SECRET_RE = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|rcon\.password)\s*[=:]\s*\S+")
def logs(sid, lines):
    srv = next((s for s in minecraft()["servers"] if s["id"] == sid), None)
    if not srv: return None
    p = os.path.join(srv["dir"], "logs", "latest.log")
    try:
        with open(p, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 400_000)); data = f.read().decode("utf-8", "replace")
    except Exception as e: return {"server": sid, "lines": [], "error": str(e)}
    out = [SECRET_RE.sub(r"\1=***", IP_RE.sub(r"\1.\2.x.x", l)) for l in data.splitlines()[-lines:]]
    return {"server": sid, "lines": out}

def chat(body):
    msgs = body.get("messages") or []
    if not isinstance(msgs, list) or len(json.dumps(msgs)) > 60_000: raise ValueError("bad messages")
    msgs = [{"role": m.get("role", "user") if m.get("role") in ("system", "user", "assistant") else "user", "content": str(m.get("content", ""))[:8000]} for m in msgs[-24:]]
    req = urllib.request.Request(CFG["ollama"] + "/api/chat", data=json.dumps({"model": CFG["model"], "messages": msgs, "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.6, "num_thread": int(os.environ.get("DOJO_AI_THREADS", "4"))}, "keep_alive": "5m"}).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=180) as r: j = json.loads(r.read())
    return {"model": CFG["model"], "reply": j.get("message", {}).get("content", ""), "ms": int((time.time() - t) * 1000)}

def ollama_status():
    try:
        with urllib.request.urlopen(CFG["ollama"] + "/api/tags", timeout=2) as r:
            return {"up": True, "model": CFG["model"], "models": [m["name"] for m in json.loads(r.read()).get("models", [])]}
    except Exception: return {"up": False, "model": CFG["model"]}

# ---------------- http ----------------
class H(http.server.BaseHTTPRequestHandler):
    server_version = "dojo-agent/" + VERSION
    def log_message(self, f, *a): pass
    def cors(self):
        o = self.headers.get("Origin")
        if o and o in CFG["origins"]:
            self.send_header("Access-Control-Allow-Origin", o); self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); self.send_header("Access-Control-Max-Age", "600")
    def send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.cors()
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204); self.cors(); self.end_headers()
    def authed(self):
        a = self.headers.get("Authorization", "")
        return bool(CFG["token"]) and hmac.compare_digest(a, "Bearer " + CFG["token"])
    def route(self, method):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/health": return self.send(200, {"ok": True, "agent": VERSION})
        if not self.authed(): return self.send(401, {"error": "unauthorized"})
        try:
            if method == "GET" and u.path == "/api/system": return self.send(200, system_info())
            if method == "GET" and u.path == "/api/minecraft": return self.send(200, minecraft())
            if method == "GET" and u.path == "/api/overview": return self.send(200, {"agent": VERSION, "system": system_info(), "minecraft": minecraft(), "ai": ollama_status()})
            if method == "GET" and u.path == "/api/logs":
                r = logs(q.get("server", [""])[0], max(1, min(500, int(q.get("lines", ["150"])[0]))))
                return self.send(200, r) if r else self.send(404, {"error": "unknown server"})
            if method == "POST" and u.path == "/api/chat":
                n = int(self.headers.get("Content-Length", 0))
                if n > 100_000: return self.send(413, {"error": "too large"})
                return self.send(200, chat(json.loads(self.rfile.read(n) or b"{}")))
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(502 if "chat" in u.path else 500, {"error": str(e)[:200]})
    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")

class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True; allow_reuse_address = True

if __name__ == "__main__":
    if not CFG["token"] or len(CFG["token"]) < 24: raise SystemExit("DOJO_TOKEN missing or too short")
    srv = S((CFG["bind"], CFG["port"]), H)
    if CFG["cert"]:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(CFG["cert"], CFG["key"]); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"dojo-agent {VERSION} on {'https' if CFG['cert'] else 'http'}://{CFG['bind']}:{CFG['port']}", flush=True)
    srv.serve_forever()

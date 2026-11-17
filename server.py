import http.server, subprocess, json, os, platform, secrets, webbrowser, threading, mimetypes, tempfile, re, urllib.parse, urllib.request, base64
import html as ihtml, shutil, time, atexit
import gapi
try:
    import pty, fcntl, termios, struct, shlex
except ImportError:
    pty = None
D = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.join(D, "apps"); os.makedirs(APPS, exist_ok=True)
TOKEN = secrets.token_urlsafe(16); CWD = [APPS]

def rp(path):
    """Resolve a path inside apps/, or inside the Jarvis folder when prefixed with @self/ (self-editing)."""
    path = (path or "").replace("\\", "/").lstrip("/")
    base, rel = (D, path[6:]) if path.startswith("@self/") else (APPS, path)
    p = os.path.abspath(os.path.join(base, rel))
    return p if p == base or p.startswith(base + os.sep) else None

MEM = os.path.join(D, "memory.json")

def web(url, data=None, headers=None, t=15):
    r = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 Jarvis", **(headers or {})})
    return urllib.request.urlopen(r, timeout=t).read()

def plain(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h); h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", ihtml.unescape(h)).strip()

def memory():
    try: return json.load(open(MEM, encoding="utf8"))
    except Exception: return []

def extra(P, d):
    if P == "/fetch":
        u = d.get("url", "")
        if not u.startswith(("http://", "https://")): return {"ok": False, "error": "URL must start with http:// or https://"}
        return {"ok": True, "text": plain(web(u).decode("utf8", "replace"))[:6000]}
    if P == "/search":
        q = d.get("q", "")
        if d.get("key"):
            j = json.loads(web("https://api.tavily.com/search", json.dumps({"api_key": d["key"], "query": q, "max_results": 5}).encode(), {"Content-Type": "application/json"}))
            return {"ok": True, "results": [{"title": x["title"], "url": x["url"], "snippet": x["content"][:300]} for x in j.get("results", [])]}
        h = web("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)).decode("utf8", "replace"); res = []
        for m in re.finditer(r'class="result__a" href="([^"]+)">(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', h, re.S):
            u = m.group(1); mm = re.search(r"uddg=([^&]+)", u); u = urllib.parse.unquote(mm.group(1)) if mm else u
            res.append({"title": plain(m.group(2)), "url": u, "snippet": plain(m.group(3))[:300]})
            if len(res) >= 6: break
        return {"ok": True, "results": res} if res else {"ok": False, "error": "No results (DuckDuckGo may be rate-limiting; add a Tavily key in Settings)"}
    if P == "/weather":
        g = json.loads(web("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(d.get("city", ""))))
        if not g.get("results"): return {"ok": False, "error": "City not found"}
        c = g["results"][0]
        w = json.loads(web(f"https://api.open-meteo.com/v1/forecast?latitude={c['latitude']}&longitude={c['longitude']}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=3"))
        return {"ok": True, "place": f"{c['name']}, {c.get('country', '')}", "current": w["current"], "daily": w["daily"]}
    if P == "/mem":
        m = memory(); op = d.get("op")
        if op == "add": m.append(d.get("text", "")[:300])
        elif op == "clear": m = []
        elif op == "del": m = [x for i, x in enumerate(m) if i != d.get("i")]
        if op in ("add", "clear", "del"): json.dump(m, open(MEM, "w", encoding="utf8"))
        return {"ok": True, "mem": m}
    if P == "/telegram":
        web(f"https://api.telegram.org/bot{d['token']}/sendMessage", urllib.parse.urlencode({"chat_id": d["chat"], "text": d["text"]}).encode())
        return {"ok": True}
    if P == "/upload":
        n = re.sub(r"[^\w.\- ]", "_", os.path.basename(d.get("name", "file")))
        p = os.path.join(APPS, "uploads", n); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(base64.b64decode(d.get("b64", ""))); return {"ok": True, "path": "uploads/" + n}


MARK = re.compile(rb"\x1b\]777;jv;(\d+);([^\x07]*)\x07")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>]")
PS1 = r"\[\e]777;jv;$?;$PWD\a\]\[\e[1;32m\]jarvis\[\e[0m\] \[\e[1;34m\]\w\[\e[0m\] \$ "

class Term:
    """One persistent real shell (PTY on Linux/macOS). The user and the AI both type into it."""
    def __init__(s):
        s.cv = threading.Condition(); s.runl = threading.Lock(); s.cols, s.rows = 100, 24; s.p = None; s.m = None; s.gen = 0
        s.ok = bool(pty and shutil.which("bash")); s.alive = False; s.cwd = APPS; s.env_sig = None
        s.buf = bytearray(); s.base = s.scan = s.np = s.code = 0; s.busy = False
        s.start()
    def set_size(s, m):
        try: fcntl.ioctl(m, termios.TIOCSWINSZ, struct.pack("HHHH", s.rows, s.cols, 0, 0))
        except Exception: pass
    def start(s):
        with s.cv:
            s.gen += 1; g = s.gen; s.buf = bytearray(); s.base = s.scan = 0; s.busy = False; s.env_sig = None
        try:
            if s.ok:
                m, sl = pty.openpty(); s.set_size(m)
                env = {**os.environ, "TERM": "xterm-256color", "PS1": PS1, "COLUMNS": str(s.cols), "LINES": str(s.rows), "HISTFILE": "/dev/null"}
                def pre():
                    import signal
                    for sg in (signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP, signal.SIGTTIN, signal.SIGTTOU):
                        try: signal.signal(sg, signal.SIG_DFL)
                        except Exception: pass
                    os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0)
                s.p = subprocess.Popen([shutil.which("bash"), "--noprofile", "--norc", "--noediting", "-i"], stdin=sl, stdout=sl, stderr=sl, cwd=APPS, env=env, preexec_fn=pre, close_fds=True)
                os.close(sl); s.m = m; s.busy = True
                src = lambda n, m=m: os.read(m, n)
            else:
                shell = ["cmd.exe"] if os.name == "nt" else [shutil.which("sh") or "/bin/sh", "-i"]
                s.p = subprocess.Popen(shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=APPS, bufsize=0)
                s.m = None; p = s.p; src = lambda n, p=p: p.stdout.read(n)
            s.alive = True
            threading.Thread(target=s.reader, args=(src, g), daemon=True).start()
            if s.ok:
                with s.cv:
                    t_end = time.time() + 3
                    while s.np == 0 and time.time() < t_end: s.cv.wait(0.1)
        except Exception as e:
            s.alive = False; s.inject("Terminal failed to start: %s\r\n" % e)
    def reader(s, src, g):
        while True:
            try: d = src(8192)
            except Exception: break
            if not d: break
            with s.cv:
                if g != s.gen: return
                s.buf += d
                if len(s.buf) > 600000:
                    cut = len(s.buf) - 400000; del s.buf[:cut]; s.base += cut
                for mt in MARK.finditer(s.buf, max(0, s.scan - s.base)):
                    s.code = int(mt.group(1)); s.np += 1; s.busy = False
                    try:
                        cw = mt.group(2).decode()
                        if os.path.isdir(cw): s.cwd = cw; CWD[0] = cw
                    except Exception: pass
                    s.scan = s.base + mt.end()
                s.cv.notify_all()
        if g == s.gen:
            s.alive = False; s.inject("\r\n[shell exited - press Restart]\r\n")
    def write(s, data):
        if not s.alive: return
        try:
            if s.m is not None: os.write(s.m, data)
            else:
                s.p.stdin.write(data.replace(b"\n", b"\r\n") if os.name == "nt" else data); s.p.stdin.flush()
        except Exception: pass
        if s.ok and (b"\n" in data or b"\r" in data): s.busy = True
    def read(s, pos, wait=0.4):
        with s.cv:
            end = s.base + len(s.buf)
            if pos > end or pos < s.base: pos = s.base
            if end <= pos: s.cv.wait(wait)
            end = s.base + len(s.buf)
            if pos > end or pos < s.base: pos = s.base
            return bytes(s.buf[pos - s.base:]), end
    def inject(s, text):
        with s.cv:
            s.buf += text.replace("\r\n", "\n").replace("\n", "\r\n").encode(); s.cv.notify_all()
    def resize(s, cols, rows):
        s.cols, s.rows = max(20, min(400, cols)), max(5, min(120, rows))
        if s.m is not None: s.set_size(s.m)
    def kill(s):
        try:
            if s.p and s.p.poll() is None:
                if s.ok: os.killpg(s.p.pid, 9)
                else: s.p.kill()
        except Exception: pass
        try:
            if s.m is not None: os.close(s.m)
        except Exception: pass
    def restart(s):
        with s.cv: s.gen += 1
        s.kill(); s.start()
    def _exec(s, cmd, timeout):
        with s.cv: start = s.base + len(s.buf); n0 = s.np
        s.write((cmd.rstrip("\n") + "\n").encode())
        end_t = time.time() + timeout
        with s.cv:
            while s.np <= n0 and time.time() < end_t and s.alive: s.cv.wait(0.2)
            done = s.np > n0; raw = bytes(s.buf[max(start, s.base) - s.base:]); code = s.code
        mt = MARK.search(raw)
        if mt: raw = raw[:mt.start()]
        txt = ANSI.sub("", raw.decode("utf8", "replace")).replace("\r\n", "\n")
        lines = [ln.split("\r")[-1] for ln in txt.split("\n")]
        if lines and lines[0].strip() == cmd.strip().split("\n")[0].strip(): lines = lines[1:]
        out = "\n".join(lines).strip("\n")
        res = {"code": code if done else 0, "stdout": out[-8000:], "stderr": "", "cwd": s.cwd}
        if not done: res["stdout"] += "\n[still running in the Terminal; it keeps going there. Press Ctrl+C in the Terminal to stop it.]"
        return res
    def run(s, cmd, env, timeout=25):
        if not (s.ok and s.alive) or s.busy or not s.runl.acquire(False): return None
        try:
            if env:
                sig = json.dumps(env, sort_keys=True)
                if sig != s.env_sig:
                    s.env_sig = sig; fp = os.path.join(D, ".jv_env")
                    with open(fp, "w") as f:
                        for k, v in env.items():
                            if re.fullmatch(r"[A-Za-z_]\w*", str(k)): f.write("export %s=%s\n" % (k, shlex.quote(str(v))))
                    os.chmod(fp, 0o600); s._exec(" . " + shlex.quote(fp), 10)
            return s._exec(cmd, timeout)
        finally: s.runl.release()

TERM = []
def term():
    if not TERM: TERM.append(Term())
    return TERM[0]
atexit.register(lambda: TERM and TERM[0].kill())

class H(http.server.BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def out(s, code, body, ct="application/json"):
        b = body.encode() if isinstance(body, str) else body
        s.send_response(code); s.send_header("Content-Type", ct); s.send_header("Cache-Control", "no-store")
        s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_GET(s):
        u = urllib.parse.unquote(s.path.split("?")[0]); qs = urllib.parse.parse_qs(urllib.parse.urlparse(s.path).query)
        if u == "/" and "state" in qs and ("code" in qs or "error" in qs):
            try:
                if "error" in qs: raise gapi.GErr("Google said: " + qs["error"][0])
                em = gapi.finish(qs["code"][0], qs["state"][0]); msg, ok = "Google connected" + (" as " + em if em else "") + ". You can close this tab and go back to Jarvis.", True
            except Exception as e: msg, ok = "Could not connect: %s" % e, False
            pg = '<!doctype html><meta charset="utf-8"><title>Jarvis</title><body style="font:18px system-ui;background:#131314;color:#e6e6e8;display:grid;place-items:center;height:100vh;margin:0"><div style="text-align:center;max-width:460px;padding:30px;border-radius:28px;background:#1e1f20"><h2 style="margin:0 0 10px;color:%s">%s</h2><p>%s</p></div>' % ("#6fcf97" if ok else "#f28b82", "Connected" if ok else "Failed", ihtml.escape(msg))
            return s.out(200, pg, "text/html; charset=utf-8")
        if u == "/":
            h = open(os.path.join(D, "index.html"), encoding="utf8").read().replace("__TOKEN__", TOKEN)
            return s.out(200, h, "text/html; charset=utf-8")
        if u.startswith("/apps/"):
            p = rp(u[6:])
            if p and os.path.isfile(p):
                ct = mimetypes.guess_type(p)[0] or "application/octet-stream"
                return s.out(200, open(p, "rb").read(), ct + ("; charset=utf-8" if ct.startswith("text") or "javascript" in ct else ""))
        s.out(404, "Not found", "text/plain")
    def do_POST(s):
        if s.headers.get("X-Token") != TOKEN: return s.out(403, '{"error":"bad token"}')
        d = json.loads(s.rfile.read(int(s.headers.get("Content-Length", 0))) or b"{}")
        P = s.path
        if P == "/info":
            return s.out(200, json.dumps({"os": platform.system(), "shell": "cmd" if os.name == "nt" else "bash", "cwd": CWD[0], "apps": APPS,
                "list": sorted(os.listdir(APPS))[:60], "mem": memory()[-40:], "url": f"http://127.0.0.1:{s.server.server_port}/"}))
        if P == "/ls":
            fl = []
            for r, ds, fs in os.walk(APPS):
                ds[:] = [x for x in ds if not x.startswith(".") and x not in ("node_modules", "__pycache__", "venv")]
                fl += [os.path.relpath(os.path.join(r, f), APPS).replace("\\", "/") for f in fs if not f.startswith(".")]
                if len(fl) > 400: break
            return s.out(200, json.dumps({"files": sorted(fl)}))
        if P == "/read":
            p = rp(d.get("path"))
            if not p or not os.path.isfile(p): return s.out(200, json.dumps({"ok": False, "error": "File not found"}))
            return s.out(200, json.dumps({"ok": True, "content": open(p, encoding="utf8", errors="replace").read()}))
        if P == "/write":
            p = rp(d.get("path"))
            if not p: return s.out(200, json.dumps({"ok": False, "error": "Path must stay inside the apps folder (or start with @self/)"}))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf8", newline="\n") as f: f.write(d.get("content", ""))
            return s.out(200, json.dumps({"ok": True, "path": p}))
        if P.startswith("/google/"):
            try:
                if P == "/google/status": return s.out(200, json.dumps(gapi.status()))
                if P == "/google/auth-url":
                    return s.out(200, json.dumps({"ok": True, "url": gapi.auth_url("http://127.0.0.1:%d/" % s.server.server_port, d.get("client_id"), d.get("client_secret"))}))
                if P == "/google/disconnect": gapi.disconnect(); return s.out(200, '{"ok": true}')
                if P == "/google/do": return s.out(200, json.dumps(gapi.run(d.get("kind", ""), d.get("spec") or {}, d.get("tz"), rp)))
            except Exception as e: return s.out(200, json.dumps({"ok": False, "error": str(e)}))
        if P.startswith("/term/"):
            t = term()
            if P == "/term/read":
                data, end = t.read(int(d.get("pos", 0)))
                return s.out(200, json.dumps({"data": base64.b64encode(data).decode(), "pos": end, "pty": t.ok, "busy": t.busy, "alive": t.alive, "cwd": t.cwd}))
            if P == "/term/write": t.write(d.get("data", "").encode())
            elif P == "/term/restart": t.restart()
            elif P == "/term/resize": t.resize(int(d.get("cols", 100)), int(d.get("rows", 24)))
            return s.out(200, '{"ok": true}')
        if P == "/run":
            c = d.get("cmd", "").strip()
            r = term().run(c, d.get("env") or {})
            if r is not None: return s.out(200, json.dumps(r))
            if c.startswith("cd ") and not any(x in c for x in ("&", ";", "|")):
                p = os.path.abspath(os.path.join(CWD[0], os.path.expanduser(c[3:].strip().strip('"'))))
                ok = os.path.isdir(p)
                if ok: CWD[0] = p
                return s.out(200, json.dumps({"code": 0 if ok else 1, "stdout": p if ok else "", "stderr": "" if ok else "No such directory: " + p, "cwd": CWD[0]}))
            fo, fe = tempfile.TemporaryFile(), tempfile.TemporaryFile()
            kw = {"creationflags": 0x200} if os.name == "nt" else {"start_new_session": True}
            env = {**os.environ, **{str(k): str(v) for k, v in (d.get("env") or {}).items()}}
            p = subprocess.Popen(c, shell=True, cwd=CWD[0], stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, env=env, **kw)
            try: p.wait(20); bg = False
            except subprocess.TimeoutExpired: bg = True
            def rd(f): f.seek(0); return f.read().decode("utf8", "replace")[-8000:]
            res = {"code": 0 if bg else p.returncode, "stdout": rd(fo), "stderr": rd(fe), "cwd": CWD[0]}
            if bg: res["stdout"] += "\n[still running in the background after 20s, pid %d]" % p.pid
            try: term().inject("\x1b[1;36m[AI]\x1b[0m $ " + c + "\n" + (res["stdout"] + res["stderr"]).replace("\r\n", "\n") + "\n")
            except Exception: pass
            return s.out(200, json.dumps(res))
        if P in ("/search", "/fetch", "/weather", "/mem", "/telegram", "/upload"):
            try: return s.out(200, json.dumps(extra(P, d)))
            except Exception as e: return s.out(200, json.dumps({"ok": False, "error": str(e)}))
        if P in ("/mail/send", "/mail/inbox"):
            try:
                if P == "/mail/send":
                    import smtplib; from email.message import EmailMessage
                    m = EmailMessage(); m["From"] = d["user"]; m["To"] = d["to"]; m["Subject"] = d.get("subject", "")
                    m.set_content(re.sub(r"<[^>]+>", "", d.get("body", "")))
                    if d.get("html"): m.add_alternative(d["body"], subtype="html")
                    with smtplib.SMTP_SSL(d.get("smtp") or "smtp.gmail.com", 465) as x: x.login(d["user"], d["pw"]); x.send_message(m)
                    return s.out(200, json.dumps({"ok": True}))
                import imaplib, email; from email.header import decode_header, make_header
                M = imaplib.IMAP4_SSL(d.get("imap") or "imap.gmail.com"); M.login(d["user"], d["pw"]); M.select("INBOX", readonly=True)
                ids = M.search(None, "ALL")[1][0].split()[-int(d.get("n") or 5):]; out = []
                for i in reversed(ids):
                    msg = email.message_from_bytes(M.fetch(i, "(RFC822)")[1][0][1])
                    part = next((q for q in msg.walk() if q.get_content_type() == "text/plain"), msg)
                    out.append({"from": msg["From"], "date": msg["Date"], "subject": str(make_header(decode_header(msg["Subject"] or ""))),
                                "text": (part.get_payload(decode=True) or b"").decode("utf8", "replace")[:500]})
                M.logout(); return s.out(200, json.dumps({"ok": True, "mails": out}))
            except Exception as e: return s.out(200, json.dumps({"ok": False, "error": str(e)}))
        s.out(404, "{}")

try: srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H)
except OSError: srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
url = f"http://127.0.0.1:{srv.server_port}/"
print(f"\n  Jarvis is running  ->  {url}\n  Apps folder: {APPS}\n  Press Ctrl+C to stop.\n")
threading.Timer(1, lambda: webbrowser.open(url)).start()
try: srv.serve_forever()
except KeyboardInterrupt: pass

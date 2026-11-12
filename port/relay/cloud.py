"""cloud.py -- cloud saves for the MC3 web port: a locker of encrypted save files per passphrase.

The host never sees a passphrase or a save. The page (web/social.js, mc3cloud) turns the
player's passphrase into three values with PBKDF2: a locker id, an AES key and a write token.
It sends the locker id, the write token and the save .zip encrypted with the key; the relay
keeps the encrypted blob and the write token's hash, nothing else.

    GET  /cloud/<id>            the newest blob (404: no locker yet)
    GET  /cloud/<id>/info       {size, t, versions}
    PUT  /cloud/<id>            body = blob, header X-Cloud-Write = write token. The first PUT
                                makes the locker; later ones need the same token.

Files: <data dir>/cloud/<id>/<time>.bin, the last KEEP kept, plus write.sha256. The data dir
is the social database's folder (~/mc3-web in WSL).
"""
import hashlib, os, pathlib, re, time
from collections import defaultdict, deque
from aiohttp import web

MAX_BLOB = 8 << 20          # one save set (MC3's profile is ~100 KB; real Xbox folders more)
KEEP = 5                    # versions kept per locker
PUTS_PER_HOUR = 60          # per address
MAX_LOCKERS_TOTAL_MB = 4096
ID_RX = re.compile(r"^[0-9a-f]{64}$")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type, X-Cloud-Write",
        "Access-Control-Allow-Methods": "GET, PUT, OPTIONS", "Access-Control-Expose-Headers": "X-Cloud-Time",
        "Cache-Control": "no-store", "Cross-Origin-Resource-Policy": "cross-origin"}
root = None
_puts = defaultdict(deque)


def _dir(i):
    return root / i


def _versions(d):
    return sorted(d.glob("*.bin"))


async def get(request):
    i = request.match_info["id"]
    if not ID_RX.match(i):
        return web.Response(status=400, headers=CORS)
    v = _versions(_dir(i)) if _dir(i).is_dir() else []
    if not v:
        return web.Response(status=404, text="no locker", headers=CORS)
    if request.match_info.get("info"):
        return web.json_response({"size": v[-1].stat().st_size, "t": int(v[-1].stem) / 1000, "versions": len(v)}, headers=CORS)
    return web.Response(body=v[-1].read_bytes(), content_type="application/octet-stream",
                        headers=dict(CORS, **{"X-Cloud-Time": str(int(v[-1].stem) / 1000)}))


async def put(request):
    i = request.match_info["id"]
    tok = request.headers.get("X-Cloud-Write", "")
    if not ID_RX.match(i) or len(tok) < 32:
        return web.Response(status=400, text="bad locker", headers=CORS)
    ip = request.headers.get("Cf-Connecting-Ip") or request.remote or ""
    q, now = _puts[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= PUTS_PER_HOUR:
        return web.Response(status=429, text="too many uploads; try later", headers=CORS)
    body = await request.content.read(MAX_BLOB + 1)
    if len(body) > MAX_BLOB or len(body) < 16 or body[:4] != b"MC3C":
        return web.Response(status=413 if len(body) > MAX_BLOB else 400, text="not a cloud save", headers=CORS)
    d = _dir(i); th = hashlib.sha256(tok.encode()).hexdigest()
    wf = d / "write.sha256"
    if wf.is_file():
        if wf.read_text().strip() != th:
            return web.Response(status=403, text="wrong passphrase for this locker", headers=CORS)
    else:
        used = sum(f.stat().st_size for f in root.glob("*/*.bin")) >> 20
        if used > MAX_LOCKERS_TOTAL_MB:
            return web.Response(status=507, text="the host is full", headers=CORS)
        d.mkdir(parents=True, exist_ok=True); wf.write_text(th)
    q.append(now)
    t = int(now * 1000)
    (d / ("%d.bin" % t)).write_bytes(body)
    for old in _versions(d)[:-KEEP]:
        old.unlink(missing_ok=True)
    return web.json_response({"ok": True, "t": t / 1000, "size": len(body)}, headers=CORS)


async def options(request):
    return web.Response(headers=CORS)


def install(app, data_dir):
    global root
    root = pathlib.Path(data_dir) / "cloud"
    root.mkdir(parents=True, exist_ok=True)
    app.router.add_get("/cloud/{id}", get)
    app.router.add_get("/cloud/{id}/{info:info}", get)
    app.router.add_put("/cloud/{id}", put)
    app.router.add_route("OPTIONS", "/cloud/{id}", options)

#!/usr/bin/env python3
"""Dev server for the WebAssembly build.

  /              web/index.html
  /mcdub3.js     the build (work-dub/build-web), .wasm beside it
  /disc/<name>   the disc importer (web/disc: disc-import.js worker, disc-core.js)
  /game/<path>   your extracted disc, with Range support (the page uses it with
                 no picker whenever the server offers it)
  /dev/disc.iso  development, with --dev-iso <file>: a disc image for testing
                 the importer end to end (the page's ?DEVISO=1)

Every response is cross-origin isolated (COOP/COEP), which SharedArrayBuffer
and so the game's threads need.

Public: the page, the build (mcdub3.js/.wasm), the disc importer, the minimap PNGs
AND the owner's extracted disc under /game are served to everyone, so a visitor's
game starts with no disc step (the owner's decision, 2026-11-10: "stream to
everyone"). Set MC3_DISC_LOCAL_ONLY=1 to go back to serving /game only to this
computer (visitors then import their own disc). The raw image at /dev/disc.iso
stays local-only either way.
"""
import argparse, collections, hashlib, json, os, pathlib, mimetypes, time
from aiohttp import web
import re

# --- access: everything the game needs is public, the extracted disc included.
# A request that came in through the Cloudflare tunnel carries Cf-Connecting-Ip /
# Cf-Ray; with MC3_DISC_LOCAL_ONLY=1 those are refused the disc files again. ---
DISC_LOCAL_ONLY = os.environ.get("MC3_DISC_LOCAL_ONLY", "") == "1"
def via_tunnel(request):
    return bool(request.headers.get("Cf-Connecting-Ip") or request.headers.get("Cf-Ray"))

# The multiplayer relay is a separate, hostable service (relay/relay.py, the
# NFSU2 session's build): WS /lan?room=<id> forwards frames between players.
# Run it with `python relay/relay.py --port 8090`. The page connects there.

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parent.parent))   # the repository root
ap.add_argument("--port", type=int, default=8099)
ap.add_argument("--dev-iso", default=None)
ap.add_argument("--build", default=None)
a = ap.parse_args()
repo = pathlib.Path(a.repo)
# The engine players get is the pinned copy in work-dub/build-web-live when there is one,
# not the build folder itself: a rebuild must not reach players before it has been tried
# (try one with `serve.py --port 8098 --build work-dub/build-web`, then copy its
# mcdub3.js/.wasm into build-web-live to release it).
_live = repo / "work-dub" / "build-web-live"
build = pathlib.Path(a.build) if a.build else (_live if (_live / "mcdub3.wasm").is_file() else repo / "work-dub" / "build-web")
if not build.is_absolute():
    build = repo / build
game = (repo / "game").resolve()
mimetypes.add_type("application/wasm", ".wasm")

_recent = collections.deque(maxlen=4000)

@web.middleware
async def isolate(request, handler):
    t0 = time.time()
    resp = await handler(request)
    print(request.method, request.path_qs, request.headers.get("Range", ""), resp.status, flush=True)
    # what actually reaches this computer (anything Cloudflare's edge answered never does):
    # /dev/requests, on this computer only, lists the recent ones
    _recent.append((round(t0, 2), request.method, request.path, resp.status,
                    resp.content_length or 0, "tunnel" if via_tunnel(request) else "local"))
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    # /engine/, /js/, /gc/: the site (same site, another origin) pre-downloads these while the
    # player is still on it (mc3-browser index.html "warm"), into the same browser cache the game
    # tab then reads from. Same-site only; everything else stays same-origin.
    # "/" too: the site (dubedition.xyz) starts the game page in a frame behind its own page once the
    # player has a username (?PRELOAD=1), so the game's start happens before Play Online.
    resp.headers["Cross-Origin-Resource-Policy"] = "same-site" if (request.path == "/" or request.path.startswith(("/engine/", "/js/", "/gc/"))) else "same-origin"
    resp.headers.setdefault("Cache-Control", "no-cache")   # handlers may opt in to caching
    return resp

# --- the engine, cacheable at Cloudflare's edge -----------------------------------------
# mcdub3.wasm is ~54 MB (12 MB brotli). Served as /mcdub3.wasm it is never edge-cached
# (.wasm is not on Cloudflare's default list) and every visitor pulls it off the host's
# upload (~25 s). So the page asks /engine.json for the current build's versioned URL,
# /engine/<version>/mcdub3.bin: a .bin IS edge-cached by default, the version in the path
# makes it safe to cache for a year, and the bytes and application/wasm type are the same.
def engine_version(b=None):
    st = ((b or build) / "mcdub3.wasm").stat()
    return f"{int(st.st_mtime):x}-{st.st_size:x}"

# A rebuild waiting to be released (work-dub/build-web, when players are on the pinned
# copy) can be tried on the real site without anyone else getting it: the page asks for
# it with ?ENGINE=next (engine.json?build=next), and its files have their own versioned URLs.
NEXT = repo / "work-dub" / "build-web"
def builds():
    return [build] + ([NEXT] if NEXT != build and (NEXT / "mcdub3.wasm").is_file() else [])

async def engine_json(request):
    try:
        b = builds()[-1] if request.query.get("build") == "next" else build
        v = engine_version(b)
        size = (b / "mcdub3.wasm").stat().st_size
    except OSError:
        raise web.HTTPNotFound()
    # size: the decoded byte count, which is what the page's download bar counts.
    # js: the engine's script under a versioned path too. As plain /mcdub3.js, Cloudflare
    # hands browsers a 4-hour lifetime for it, so after an update returning players kept
    # running the old script (and its old disc reader) for hours.
    out = {"v": v, "wasm": f"/engine/{v}/engine.bin", "size": size}
    try:
        out["js"] = f"/js/{js_version(b)}/mcdub3.js"
    except OSError:
        pass
    return _cars_cors(request, web.json_response(out))

def js_version(b=None):
    p = (b or build) / "mcdub3.js"
    text = patched_js(p)
    return f"{int(p.stat().st_mtime):x}-{hashlib.sha1(text.encode()).hexdigest()[:10]}"

def build_for(version_of, v):
    """The build whose file has this version (the players' one or the one being tried)."""
    for b in builds():
        try:
            if version_of(b) == v:
                return b
        except OSError:
            pass
    raise web.HTTPNotFound()              # an old build's URL: never serve new bytes under it

async def engine_js(request):
    p = build_for(js_version, request.match_info["v"]) / "mcdub3.js"
    return web.Response(text=patched_js(p), content_type="text/javascript", headers={"Cache-Control": IMMUTABLE})

async def engine_wasm(request):
    p = build_for(engine_version, request.match_info["v"]) / "mcdub3.wasm"
    resp = web.FileResponse(p, chunk_size=1 << 20)
    resp.content_type = "application/wasm"
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp

async def index(request):
    return web.FileResponse(repo / "web" / "index.html")

# --- the disc, cacheable at Cloudflare's edge --------------------------------------------
# The engine reads the disc in 1 MB pieces with Range requests on /game/<path>. Cloudflare
# never caches those (a Range on an uncached file goes to the origin every time), so every
# player pulled every megabyte off the host's upload. Same cure as the engine: each piece
# gets its own versioned URL ending in .bin,
#     /gc/<disc version>/<piece number>/<path>.bin      (a plain 200, immutable)
# which Cloudflare keeps at its edge after the first request. /mcdub3.js is served with
# its disc reader patched to ask for those (and to take file sizes from one cached list,
# /gc/<v>/manifest.bin, instead of a HEAD per file). If anything is missing the reader
# falls back to the Range requests, which still work.
CHUNK = int(os.environ.get("MC3_CHUNK", 65536))   # piece size; part of the disc version below

# No movies (the owner's decision, 2026-11-10: they stuttered for players). Every .bik is
# answered with its two-frame stand-in from game-novideo/ (tools_novideo.py makes them from
# the disc's own files), so the game is through a movie the moment it opens it. The disc
# itself is untouched; MC3_NO_VIDEO=0 serves the real movies again.
NO_VIDEO = os.environ.get("MC3_NO_VIDEO", "1") != "0"
novideo = (repo / "game-novideo").resolve()
def disc_path(rel):
    """The file to send for a path on the disc."""
    if NO_VIDEO and rel.lower().endswith(".bik"):
        p = novideo / rel
        if p.is_file():
            return p
    return game / rel

_disc = None
def disc_info():
    """(version, {relative path: size}) of the extracted disc; saves are not part of it."""
    global _disc
    if _disc is None:
        files, h = {}, hashlib.sha1(f"piece {CHUNK}\ncorp same-site\n".encode())
        if game.is_dir():
            for root, dirs, names in os.walk(game):
                dirs[:] = sorted(d for d in dirs if not (pathlib.Path(root) == game and d in ("UDATA", "TDATA", "CACHE")))
                for n in sorted(names):
                    rel = (pathlib.Path(root) / n).relative_to(game).as_posix()
                    st = disc_path(rel).stat()
                    files[rel] = st.st_size
                    h.update(f"{rel}\0{st.st_size}\0{int(st.st_mtime)}\n".encode())
        _disc = (h.hexdigest()[:12], files)
    return _disc

IMMUTABLE = "public, max-age=31536000, immutable"
_asked = {}                                  # (path, piece) in first-asked order: the boot profile recorder

async def gc_manifest(request):
    if DISC_LOCAL_ONLY:
        local_only(request)
    v, files = disc_info()
    if request.match_info["v"] != v:
        raise web.HTTPNotFound()
    return web.json_response(files, headers={"Cache-Control": IMMUTABLE})

async def gc_chunk(request):
    if DISC_LOCAL_ONLY:
        local_only(request)
    v, files = disc_info()
    rel = request.match_info["path"]
    if request.match_info["v"] != v or not rel.endswith(".bin"):
        raise web.HTTPNotFound()
    rel = rel[:-4].lstrip("/")
    idx = int(request.match_info["idx"])
    size = files.get(rel)
    if size is None or idx * CHUNK >= size:
        raise web.HTTPNotFound()
    _asked.setdefault((rel, idx), None)
    with open(disc_path(rel), "rb") as f:    # rel is a key of the disc's own file list: no traversal
        f.seek(idx * CHUNK)
        data = f.read(CHUNK)
    return web.Response(body=data, content_type="application/octet-stream", headers={"Cache-Control": IMMUTABLE})

# The boot profile: which pieces the game reads on its way to the main menu, in order
# (web/boot-profile.json, recorded here on the host: /dev/profile?reset=1, boot the game
# to its menu on http://localhost, /dev/profile?save=1). The page downloads them in
# parallel while the engine starts, so the game finds them already in the browser's cache.
PROFILE = repo / "web" / "boot-profile.json"
ONLINE_PROFILE = repo / "web" / "online-profile.json"
async def dev_profile(request):
    local_only(request)
    if "reset" in request.query:
        _asked.clear()
    v, files = disc_info()
    chunks = [[p, i] for (p, i) in _asked]
    out = {"chunks": chunks, "bytes": sum(min(CHUNK, files[p] - i * CHUNK) for p, i in chunks)}
    if "save" in request.query:
        # save=online: the second profile, recorded from the main menu through Play Online into
        # free-roam (Arcade's screen, the city): the page fetches it in the background after the
        # boot profile (index.html), so joining reads from the browser's cache too
        (ONLINE_PROFILE if request.query.get("save") == "online" else PROFILE).write_text(json.dumps(out))
    return web.json_response({"pieces": len(chunks), "bytes": out["bytes"], "saved": "save" in request.query,
                              **({"chunks": chunks} if "list" in request.query else {})})

async def dev_requests(request):
    local_only(request)
    rows = [r for r in _recent if r[5] == "tunnel" or "all" in request.query]
    if "reset" in request.query:
        _recent.clear()
    return web.json_response(rows)

# Boot reports from the page (index.html bootRep): each visit's boot milestones with times and
# frame times, kept in memory (the last 40 visits), readable on the host at /dev/boots. No
# personal data: a random visit id, times, the game's log lines, CPU cores / memory.
_boots = {}
async def boot_log(request):
    try:
        body = await request.content.read(65536)
        d = json.loads(body)
        vid = str(d.get("id", ""))[:12]
        if not vid:
            raise ValueError
        v = _boots.setdefault(vid, {"first": time.time(), "sys": d.get("sys", {}), "lines": [],
                                    "via": "tunnel" if request.headers.get("Cf-Ray") else "local"})
        v["last"] = time.time()
        if d.get("snapshot"):                      # F9 / "Report a problem": the log's last lines
            v.setdefault("snapshots", []).append({"t": time.time(), "why": str(d["snapshot"])[:80],
                                                  "lines": (d.get("q") or [])[:400]})
            del v["snapshots"][:-3]
        else:
            v["lines"].extend((d.get("q") or [])[:400])
            del v["lines"][:-1500]
        while len(_boots) > 40:
            _boots.pop(min(_boots, key=lambda k: _boots[k]["first"]))
    except Exception:
        pass
    return web.Response(status=204)

async def dev_boots(request):
    local_only(request)
    return web.json_response(sorted(_boots.items(), key=lambda kv: kv[1]["first"]))

async def boot_profile(request):
    v, files = disc_info()
    try:
        prof = json.loads((ONLINE_PROFILE if request.path == "/online-profile.json" else PROFILE).read_text())
    except (OSError, ValueError):
        prof = {"chunks": [], "bytes": 0}
    # only pieces this disc really has; the version tells the page which URLs to ask for
    prof["chunks"] = [c for c in prof.get("chunks", []) if c[0] in files and c[1] * CHUNK < files[c[0]]]
    prof["v"], prof["cs"] = v, CHUNK
    return _cars_cors(request, web.json_response(prof))

_patched_by_path = {}
def patched_js(p):
    """mcdub3.js with the fetch backend's disc reader asking for edge-cacheable pieces."""
    key = (p.stat().st_mtime, disc_info()[0])
    _patched = _patched_by_path.get(str(p), (None, None))
    if _patched[0] != key:
        src = p.read_text()
        anchor = "async function __wasmfs_create_fetch_backend_js(backend){backend>>>=0;"
        shim = (
            # mc3get: one download per piece URL, shared by whoever asks (a small recent-use
            # table). mc3last: per file, where its recent sequential readers are -- a request
            # that carries on from one is a sequential load, so the next pieces are fetched
            # ahead (2, 4, ... up to 32 = 2 MB), which keeps big loads fast even though the
            # pieces are small (details at the read-ahead below).
            # mc3try: a piece that hasn't arrived in 20 s is abandoned and asked for again (3
            # more tries, not after a 404). The game's read waits on it, so one fetch that
            # never settles (seen through the tunnel?) would otherwise freeze the game for good.
            'var mc3fetch=self.fetch.bind(self),mc3man=null,mc3pend=new Map,mc3last={};'
            'function mc3try(u,n){var ac=new AbortController(),t=setTimeout(()=>ac.abort(),20000);'
            'return mc3fetch(u,{signal:ac.signal}).then(x=>{if(!x.ok)throw x;return x.arrayBuffer()})'
            '.finally(()=>clearTimeout(t)).catch(x=>{if(n<3&&!(x&&x.status==404)){'
            'console.warn("[DISC] piece retried ("+(n+1)+"): "+u);return mc3try(u,n+1)}throw x})}'
            'function mc3get(u){var p=mc3pend.get(u);if(!p){'
            'p=mc3try(u,0);'
            'p.catch(()=>{mc3pend.delete(u)});mc3pend.set(u,p);'
            'if(mc3pend.size>320)mc3pend.delete(mc3pend.keys().next().value)}return p}'
            'async function fetch(url,opt){'
            'var m=null;try{m=/\\/game\\/+(.+)$/.exec(new URL(url,self.location.href).pathname)}catch(_e){}'
            'var rng=opt&&opt.headers&&opt.headers.Range;'
            'if(!m)return mc3fetch(url,opt);'
            'try{'
            'if(!mc3man)mc3man=mc3fetch("/gc/%(v)s/manifest.bin").then(r=>r.ok?r.json():{}).catch(()=>({}));'
            'var man=await mc3man,size=man[decodeURIComponent(m[1])];'
            # A file the disc doesn't have: "not found" at once. It went to the host twice (the
            # size check, then the whole file), with no time limit, and a player's game sat in
            # NtCreateFile up to ~25 s over 8 such opens (2026-11-12, visit 0r72jy9z). The save
            # folders (UDATA/TDATA/CACHE) aren't in the list and still go to the host.
            'if(size==null){if(Object.keys(man).length&&!/^(udata|tdata|cache)\\//i.test(decodeURIComponent(m[1])))'
            'return new Response(null,{status:404});return mc3fetch(url,opt)}'
            'if(!rng)return mc3fetch(url,opt);'
            'if(opt.method==="HEAD")return{ok:true,headers:{has:()=>true,get:h=>h=="Content-Length"?String(size):"bytes"}};'
            'var r=/bytes=(\\d+)-(\\d+)/.exec(rng),CS=%(cs)d;if(!r)return mc3fetch(url,opt);'
            'var s=+r[1],e=Math.min(+r[2]+1,size);if(s%%CS||s>=e)return mc3fetch(url,opt);'
            'var U=c=>"/gc/%(v)s/"+c+"/"+m[1]+".bin",parts=[],c=s/CS;for(;c*CS<e;c++)parts.push(mc3get(U(c)));'
            # Several readers can walk one file at once (a movie is read by the game's Bink
            # and by the native decoder, each at its own place), so a file has up to 8
            # streams; a request that lands on a stream's next piece, or inside what was
            # fetched ahead for it, continues it. Movies and audio banks are always read
            # front to back: they start with 8 pieces ahead and go up to 64 (4 MB).
            'var S=mc3last[m[1]]||(mc3last[m[1]]=[]),c0=s/CS,st=null,av=/\\.(bik|xwb)$/i.test(m[1]),mx=av?64:32;'
            'for(var k=0;k<S.length;k++)if(c0>=S[k].next-1&&c0<=S[k].next+S[k].ah){st=S[k];break}'
            'if(st)st.ah=Math.min(mx,Math.max(2,st.ah*2));else{st={next:0,ah:av?8:0};S.push(st);if(S.length>8)S.shift()}'
            'st.next=c;'
            'for(var a=c;a<c+st.ah&&a*CS<size;a++)mc3get(U(a)).catch(()=>{});'
            'var bufs=await Promise.all(parts),out=new Uint8Array(e-s),o=0;'
            'for(var b of bufs){out.set(new Uint8Array(b),o);o+=b.byteLength}'
            'if(o!==e-s)return mc3fetch(url,opt);'
            'return{ok:true,arrayBuffer:async()=>out.buffer}'
            '}catch(_e){return mc3fetch(url,opt)}}'
        ) % {"v": disc_info()[0], "cs": CHUNK}
        # The piece size the engine was built with (1 MB) made a boot download 75 MB to
        # read 6 MB: every small read pulled a whole megabyte. The reader takes ours instead.
        size_call = "var chunkSize=__wasmfs_fetch_get_chunk_size(file);"
        if src.count(anchor) == 1 and src.count(size_call) == 1:
            src = src.replace(anchor, anchor + shim).replace(size_call, "var chunkSize=%d;" % CHUNK)
        else:
            print("WARNING: mcdub3.js fetch backend not found; disc pieces will not be edge-cached", flush=True)
        _patched = _patched_by_path[str(p)] = (key, src)
    return _patched[1]

async def build_file(request):
    name = request.match_info["name"]
    p = build / name
    if not p.is_file():
        raise web.HTTPNotFound()
    if name == "mcdub3.js":
        return web.Response(text=patched_js(p), content_type="text/javascript")
    return web.FileResponse(p)

# The cars the game's Arcade car-select offers (index.html mc3menu reads them off the screen
# during Play Online and POSTs them here). The site's Play Online card fetches GET /cars to
# fill its Vehicle picker. Only the host computer's own page may record the list (a visitor
# through the tunnel can't plant names); anyone may read it. Kept in web/cars.json.
CARS = repo / "web" / "cars.json"
CARS_ORIGINS = {"https://dubedition.xyz", "https://www.dubedition.xyz", "http://localhost:8088", "http://127.0.0.1:8088"}
_CAR_NAME = re.compile(r"^[A-Za-z0-9 .,'&()/+-]{1,40}$")
def _cars_cors(request, resp):
    o = request.headers.get("Origin", "")
    if o in CARS_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = o
        resp.headers["Vary"] = "Origin"
    return resp                                   # (a CORS fetch: the isolate middleware's CORP doesn't apply)
async def cars_get(request):
    try:
        d = json.loads(CARS.read_text()) if CARS.is_file() else {"cars": []}
    except Exception:
        d = {"cars": []}
    return _cars_cors(request, web.json_response(d, headers={"Cache-Control": "public, max-age=60"}))
async def cars_post(request):
    if via_tunnel(request):
        raise web.HTTPForbidden(text="only the host computer records the car list")
    try:
        d = json.loads(await request.content.read(16384))
        cars = [str(c).strip() for c in d.get("cars", [])]
    except Exception:
        raise web.HTTPBadRequest(text="expected {\"cars\": [names]}")
    if not (1 <= len(cars) <= 120) or not all(_CAR_NAME.match(c) for c in cars):
        raise web.HTTPBadRequest(text="bad car list")
    out = {"cars": cars, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    CARS.write_text(json.dumps(out, indent=1))
    return web.json_response({"saved": len(cars)})

def local_only(request):
    """The disc's bytes stay on the host computer: never served through the
    tunnel. Players coming in over the internet import their own disc instead."""
    if via_tunnel(request):
        raise web.HTTPForbidden(text="The game's disc files are served only on the host computer; bring your own disc.")

async def game_file(request):
    if DISC_LOCAL_ONLY:
        local_only(request)
    rel = request.match_info["path"].lstrip("/")      # WasmFS asks for game//<path>
    p = (game / rel).resolve()
    if game not in p.parents or not p.is_file():
        raise web.HTTPNotFound()
    p = disc_path(p.relative_to(game).as_posix())
    resp = web.FileResponse(p, chunk_size=1 << 20)
    resp.headers["Accept-Ranges"] = "bytes"
    # (the engine's reader uses the /gc pieces below; this is the fallback path, and what
    # it returns for a file can change -- the movie stand-ins -- so browsers must re-check)
    resp.headers["Cache-Control"] = "no-cache"
    return resp

async def web_png(request):
    # the extracted minimap images (hudmap_sd.png etc.), served from web/
    p = repo / "web" / request.match_info["name"]
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})

async def flag_png(request):
    # country flags for the name tags (flagpedia.net's public-domain icons, web/flags/<cc>.png)
    p = repo / "web" / "flags" / (request.match_info["cc"] + ".png")
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})

async def font_file(request):
    # fonts the page uses (web/fonts/<name>.woff2), e.g. the crew name over players' heads
    p = repo / "web" / "fonts" / (request.match_info["name"] + ".woff2")
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=604800", "Content-Type": "font/woff2"})

async def social_js(request):
    # web/social.js: player id, crews, chat and voice (the relay side is relay/social.py)
    return web.FileResponse(repo / "web" / "social.js", headers={"Cache-Control": "no-cache", "Content-Type": "text/javascript"})

async def menu_text(request):
    # web/menu-text.json: the owner's rewording of the game's on-screen text (see index.html)
    p = repo / "web" / "menu-text.json"
    if not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p)

async def disc_file(request):
    name = request.match_info["name"]
    p = repo / "web" / "disc" / name
    if not p.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(p)
    resp.content_type = "text/javascript"
    return resp

async def dev_iso(request):
    local_only(request)
    if not a.dev_iso or not pathlib.Path(a.dev_iso).is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(a.dev_iso, chunk_size=1 << 20)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp

app = web.Application(middlewares=[isolate])
app.router.add_get("/", index)
app.router.add_get("/{name:hudmap[A-Za-z0-9_]*\\.png}", web_png)
app.router.add_get("/disc/{name:[a-z-]+\\.js}", disc_file)
app.router.add_get("/dev/disc.iso", dev_iso)
app.router.add_route("*", "/game/{path:.+}", game_file)
app.router.add_get("/{name:mcdub3\\.(js|wasm)}", build_file)
app.router.add_get("/flags/{cc:[a-z][a-z]}.png", flag_png)
app.router.add_get("/fonts/{name:[a-z0-9-]+}.woff2", font_file)
app.router.add_get("/menu-text.json", menu_text)
app.router.add_get("/social.js", social_js)
app.router.add_get("/cars", cars_get)
app.router.add_post("/cars", cars_post)
app.router.add_get("/gc/{v:[0-9a-f]+}/manifest.bin", gc_manifest)
app.router.add_get("/gc/{v:[0-9a-f]+}/{idx:[0-9]+}/{path:.+}", gc_chunk)
app.router.add_get("/boot-profile.json", boot_profile)
app.router.add_get("/online-profile.json", boot_profile)
app.router.add_get("/dev/profile", dev_profile)
app.router.add_get("/dev/requests", dev_requests)
app.router.add_post("/boot-log", boot_log)
app.router.add_get("/dev/boots", dev_boots)
app.router.add_get("/js/{v:[0-9a-f]+-[0-9a-f]+}/mcdub3.js", engine_js)
app.router.add_get("/engine.json", engine_json)
app.router.add_get("/engine/{v:[0-9a-f]+-[0-9a-f]+}/{name:(mcdub3|engine)\\.bin}", engine_wasm)
print(f"serving http://localhost:{a.port}/  (game: {game}, disc version {disc_info()[0]}, {len(disc_info()[1])} files)", flush=True)
web.run_app(app, port=a.port, print=None)

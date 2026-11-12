"""social.py -- the free-roam social layer on the relay: identity, crews, text chat and the
signalling for voice chat. Mounted on relay.py's app (make_app); no game code here either.

Identity: a page keeps a player id (pid, 32 hex) and a secret key in its browser
(localStorage mc3.pid / mc3.key). The first hello with a new pid registers it with
sha256(key); later hellos must bring the same key. That is all an "account" is: no
e-mail, no password. Losing the browser's storage loses the identity (and the crew place).

    WS  /social?room=<id>        JSON text messages, both ways (see handle()).
    GET /crews[?q=text]          [{tag, name, open, members, online, leader}]
    GET /crew/<tag>              {tag, name, open, leader, members:[{pid,name,cc,role,online}]}
    POST /crew                   {pid, key, op, ...}  the same crew operations as over WS
                                 (for the launcher site's card later)

The relay also tells this module where each player is (GHST frames carry the ghost id and
x, z; relay.py calls note_pos), for nearby chat, and asks it which crew tag a ghost may wear
(crew_for_gid): the crew text in a position frame is rewritten to the player's real crew.

Database: SQLite, MC3_SOCIAL_DB or ~/mc3-web/social.db (inside WSL: not /mnt/c, whose file
locking SQLite does not trust), else social.db beside this file.
"""
import asyncio, hashlib, json, os, pathlib, re, sqlite3, struct, time
from collections import deque
from aiohttp import web, WSMsgType

CHAT_MAX = 160            # characters per message
CHAT_BURST = 5            # messages ...
CHAT_WINDOW = 8.0         # ... per this many seconds
NEAR_M = 150.0            # nearby chat: within this many metres (world units)
POS_STALE = 5.0           # a position older than this does not count
RTC_PER_10S = 400         # voice signalling messages (offers, ICE candidates) per 10 s
SOCIAL_ROOM_MAX = 256     # social sockets per room (players + their second tabs)
CREW_MAX = 50             # members per crew
TAG_RX = re.compile(r"^[A-Za-z0-9_ ]{2,10}$")


def _db_path():
    p = os.environ.get("MC3_SOCIAL_DB")
    if p:
        return p
    home = pathlib.Path(os.path.expanduser("~/mc3-web"))
    if home.is_dir():
        return str(home / "social.db")
    return str(pathlib.Path(__file__).with_name("social.db"))


class DB:
    def __init__(self, path):
        self.c = sqlite3.connect(path, isolation_level=None)   # autocommit; tiny writes
        self.c.row_factory = sqlite3.Row
        self.c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS players (pid TEXT PRIMARY KEY, keyhash TEXT NOT NULL,
                name TEXT DEFAULT '', cc TEXT DEFAULT '', created REAL, seen REAL);
            CREATE TABLE IF NOT EXISTS crews (id INTEGER PRIMARY KEY, tag TEXT NOT NULL,
                tagkey TEXT UNIQUE NOT NULL, name TEXT DEFAULT '', open INTEGER DEFAULT 1,
                leader TEXT NOT NULL, created REAL);
            CREATE TABLE IF NOT EXISTS members (pid TEXT PRIMARY KEY, crew INTEGER NOT NULL,
                role TEXT DEFAULT 'member', joined REAL);
            CREATE TABLE IF NOT EXISTS invites (crew INTEGER, pid TEXT, by TEXT, t REAL,
                PRIMARY KEY (crew, pid));
            CREATE TABLE IF NOT EXISTS names (namekey TEXT PRIMARY KEY, name TEXT NOT NULL,
                pid TEXT UNIQUE NOT NULL, t REAL);
            CREATE TABLE IF NOT EXISTS bans (n INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, ip TEXT,
                reason TEXT DEFAULT '', until REAL, t REAL, lifted REAL);
            CREATE TABLE IF NOT EXISTS mutes (pid TEXT PRIMARY KEY, until REAL, reason TEXT DEFAULT '', t REAL);
            CREATE TABLE IF NOT EXISTS friends (a TEXT, b TEXT, t REAL, PRIMARY KEY (a, b));
            CREATE TABLE IF NOT EXISTS freqs (frm TEXT, too TEXT, t REAL, PRIMARY KEY (frm, too));
            CREATE TABLE IF NOT EXISTS pms (id INTEGER PRIMARY KEY AUTOINCREMENT, frm TEXT, too TEXT,
                text TEXT, t REAL, delivered INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS pms_to ON pms (too, delivered);
            CREATE TABLE IF NOT EXISTS results (race TEXT, pid TEXT, name TEXT, mode TEXT, city TEXT, track TEXT,
                laps INTEGER, ms INTEGER, pos INTEGER, car TEXT, t REAL, PRIMARY KEY (race, pid));
            CREATE INDEX IF NOT EXISTS results_track ON results (mode, city, track, laps, ms);
            CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, frm TEXT, frm_name TEXT,
                about TEXT, about_name TEXT, room TEXT, why TEXT, text TEXT, trail TEXT, seen INTEGER DEFAULT 0);
        """)
        cols = {r[1] for r in self.c.execute("PRAGMA table_info(players)")}
        if "ip" not in cols:
            self.c.execute("ALTER TABLE players ADD COLUMN ip TEXT DEFAULT ''")

    def q(self, sql, *a):
        return self.c.execute(sql, a).fetchall()

    def one(self, sql, *a):
        return self.c.execute(sql, a).fetchone()

    def x(self, sql, *a):
        return self.c.execute(sql, a)


db = None
clients = {}              # ws -> Client
pos = {}                  # (room, gid) -> (x, z, t)


class Client:
    __slots__ = ("ws", "room", "pid", "gid", "name", "cc", "voice", "chat_t", "rtc_t", "rtc_n", "ip", "name_note",
                 "hear", "vx_t", "vx_n", "vx_mute", "vx_aud")
    def __init__(self, ws, room, ip=""):
        self.ws = ws; self.room = room; self.pid = None; self.gid = 0; self.ip = ip; self.name_note = None
        self.name = "Player"; self.cc = ""; self.voice = False
        self.chat_t = []; self.rtc_t = 0.0; self.rtc_n = 0
        self.hear = True; self.vx_t = 0.0; self.vx_n = 0; self.vx_mute = (0.0, False); self.vx_aud = (0.0, -1, [])


def _clean(s, n, rx=r"[^A-Za-z0-9_ ]"):
    return re.sub(rx, "", str(s or "")).strip()[:n]


def _text(s):
    s = re.sub(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]", "", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:CHAT_MAX]


def crew_of(pid):
    """(crew row, role) or (None, None)"""
    m = db.one("SELECT crew, role FROM members WHERE pid=?", pid)
    if not m:
        return None, None
    return db.one("SELECT * FROM crews WHERE id=?", m["crew"]), m["role"]


def online_pids():
    return {c.pid for c in clients.values() if c.pid}


def crew_info(cr):
    on = online_pids()
    mem = db.q("SELECT m.pid, m.role, p.name, p.cc FROM members m LEFT JOIN players p ON p.pid=m.pid "
               "WHERE m.crew=? ORDER BY m.role='leader' DESC, m.joined", cr["id"])
    return {"tag": cr["tag"], "name": cr["name"], "open": bool(cr["open"]), "leader": cr["leader"],
            "members": [{"pid": r["pid"], "name": r["name"] or "Player", "cc": r["cc"] or "",
                         "role": r["role"], "online": r["pid"] in on} for r in mem]}


def me_msg(pid):
    cr, role = crew_of(pid)
    inv = db.q("SELECT c.tag, c.name, i.by, p.name AS byname FROM invites i JOIN crews c ON c.id=i.crew "
               "LEFT JOIN players p ON p.pid=i.by WHERE i.pid=? ORDER BY i.t DESC LIMIT 10", pid)
    cl = db.one("SELECT name FROM names WHERE pid=?", pid)
    return {"t": "me", "pid": pid, "crew": crew_info(cr) if cr else None, "role": role, "claimed": cl["name"] if cl else None,
            "invites": [{"tag": r["tag"], "name": r["name"], "by": r["byname"] or "Player"} for r in inv]}


def tag_of(pid):
    cr, _ = crew_of(pid)
    return cr["tag"] if cr else ""


def card(c):
    return {"pid": c.pid, "gid": c.gid, "name": c.name, "cc": c.cc, "crew": tag_of(c.pid), "v": c.voice}


async def send(ws, msg):
    if ws.closed:
        return
    try:
        await ws.send_str(json.dumps(msg, separators=(",", ":")))
    except Exception:
        pass


def fan(targets, msg):
    s = json.dumps(msg, separators=(",", ":"))
    for c in targets:
        if not c.ws.closed:
            asyncio.ensure_future(_raw(c.ws, s))


async def _raw(ws, s):
    try:
        await ws.send_str(s)
    except Exception:
        pass


def in_room(room):
    return [c for c in clients.values() if c.room == room and c.pid]


def by_pid(pid):
    return [c for c in clients.values() if c.pid == pid]


def crew_clients(crew_id):
    pids = {r["pid"] for r in db.q("SELECT pid FROM members WHERE crew=?", crew_id)}
    return [c for c in clients.values() if c.pid in pids]


def refresh_people(pids, rooms=()):
    """Players whose crew changed: send them their own state, tell their rooms."""
    for pid in pids:
        for c in by_pid(pid):
            fan([c], me_msg(pid))
            fan(in_room(c.room), {"t": "upd", "p": card(c)})


# --- the hook relay.py uses ----------------------------------------------------------------

trail = {}                # (room, gid) -> deque of (unix time, x, z), one a second: the last ~20 s, for reports


def note_pos(room, gid, x, z):
    now = time.monotonic()
    k = (room, gid)
    pos[k] = (x, z, now)
    q = trail.get(k)
    if q is None:
        if len(trail) > 4096:
            trail.clear()
        q = trail[k] = deque(maxlen=20)
    if not q or time.time() - q[-1][0] >= 1.0:
        q.append((round(time.time(), 1), round(x, 1), round(z, 1)))


_gid_tag = {}             # (room, gid) -> (tag, t): which crew a ghost may wear, cached 2 s


def ghost_ident(room, gid):
    """(name, crew tag) the ghost gid may show; None if no verified player has it. Cached 2 s."""
    now = time.monotonic()
    hit = _gid_tag.get((room, gid))
    if hit and now - hit[1] < 2.0:
        return hit[0]
    ident = None
    for c in clients.values():
        if c.room == room and c.gid == gid and c.pid:
            ident = (c.name, tag_of(c.pid)); break
    _gid_tag[(room, gid)] = (ident, now)
    if len(_gid_tag) > 4096:
        _gid_tag.clear()
    return ident


def crew_for_gid(room, gid):
    i = ghost_ident(room, gid)
    return None if i is None else i[1]


blocked_gids = set()       # (room, gid) of banned players: the relay drops their frames, closes them


def blocked(room, gid):
    return (room, gid) in blocked_gids


def _where(c):
    p = pos.get((c.room, c.gid)) if c.gid else None
    if p and time.monotonic() - p[2] < POS_STALE:
        return p
    return None


# --- crew operations ---------------------------------------------------------------------

def crew_op(pid, op, a):
    """Returns (ok, message, pids whose state changed)."""
    cr, role = crew_of(pid)
    now = time.time()
    if op == "create":
        tag = _clean(a.get("tag"), 10)
        if not TAG_RX.match(tag):
            return False, "A crew tag is 2-10 letters, digits, _ or spaces.", []
        if cr:
            return False, "Leave your crew first.", []
        if db.one("SELECT 1 FROM crews WHERE tagkey=?", tag.lower()):
            return False, "That tag is taken.", []
        cur = db.x("INSERT INTO crews (tag, tagkey, name, open, leader, created) VALUES (?,?,?,?,?,?)",
                   tag, tag.lower(), _clean(a.get("name"), 24, r"[^A-Za-z0-9_ '.-]"), 1 if a.get("open", True) else 0, pid, now)
        db.x("INSERT INTO members (pid, crew, role, joined) VALUES (?,?,?,?)", pid, cur.lastrowid, "leader", now)
        db.x("DELETE FROM invites WHERE pid=?", pid)
        return True, "Crew [%s] created. You lead it." % tag, [pid]
    if op == "join":
        tag = _clean(a.get("tag"), 10)
        t = db.one("SELECT * FROM crews WHERE tagkey=?", tag.lower())
        if not t:
            return False, "No crew with that tag.", []
        if cr and cr["id"] == t["id"]:
            return False, "You are already in [%s]." % t["tag"], []
        if cr:
            return False, "Leave your crew first.", []
        invited = db.one("SELECT 1 FROM invites WHERE crew=? AND pid=?", t["id"], pid)
        if not t["open"] and not invited:
            return False, "[%s] is invite-only." % t["tag"], []
        if db.one("SELECT COUNT(*) n FROM members WHERE crew=?", t["id"])["n"] >= CREW_MAX:
            return False, "[%s] is full." % t["tag"], []
        db.x("INSERT INTO members (pid, crew, role, joined) VALUES (?,?,?,?)", pid, t["id"], "member", now)
        db.x("DELETE FROM invites WHERE pid=?", pid)
        return True, "You joined [%s]." % t["tag"], [r["pid"] for r in db.q("SELECT pid FROM members WHERE crew=?", t["id"])]
    if op == "decline":
        tag = _clean(a.get("tag"), 10)
        db.x("DELETE FROM invites WHERE pid=? AND crew IN (SELECT id FROM crews WHERE tagkey=?)", pid, tag.lower())
        return True, "", [pid]
    if not cr:
        return False, "You are not in a crew.", []
    mates = [r["pid"] for r in db.q("SELECT pid FROM members WHERE crew=?", cr["id"])]
    if op == "leave":
        db.x("DELETE FROM members WHERE pid=?", pid)
        rest = db.q("SELECT pid FROM members WHERE crew=? ORDER BY joined", cr["id"])
        if not rest:
            db.x("DELETE FROM crews WHERE id=?", cr["id"]); db.x("DELETE FROM invites WHERE crew=?", cr["id"])
            return True, "You left [%s]; it had no one else, so it is gone." % cr["tag"], mates
        if cr["leader"] == pid:                      # the longest-standing member leads now
            db.x("UPDATE crews SET leader=? WHERE id=?", rest[0]["pid"], cr["id"])
            db.x("UPDATE members SET role='leader' WHERE pid=?", rest[0]["pid"])
        return True, "You left [%s]." % cr["tag"], mates
    if op == "invite":
        to = str(a.get("pid") or "")
        if not db.one("SELECT 1 FROM players WHERE pid=?", to):
            return False, "No such player.", []
        if db.one("SELECT 1 FROM members WHERE pid=? AND crew=?", to, cr["id"]):
            return False, "Already in your crew.", []
        db.x("INSERT OR REPLACE INTO invites (crew, pid, by, t) VALUES (?,?,?,?)", cr["id"], to, pid, now)
        nm = db.one("SELECT name FROM players WHERE pid=?", to)["name"] or "Player"
        return True, "Invited %s to [%s]." % (nm, cr["tag"]), [to]
    if cr["leader"] != pid:
        return False, "Only the crew leader can do that.", []
    if op == "kick":
        to = str(a.get("pid") or "")
        if to == pid or not db.one("SELECT 1 FROM members WHERE pid=? AND crew=?", to, cr["id"]):
            return False, "Not a member you can remove.", []
        db.x("DELETE FROM members WHERE pid=?", to)
        return True, "Removed from [%s]." % cr["tag"], mates
    if op == "leader":
        to = str(a.get("pid") or "")
        if not db.one("SELECT 1 FROM members WHERE pid=? AND crew=?", to, cr["id"]):
            return False, "Not in your crew.", []
        db.x("UPDATE crews SET leader=? WHERE id=?", to, cr["id"])
        db.x("UPDATE members SET role='member' WHERE pid=?", pid)
        db.x("UPDATE members SET role='leader' WHERE pid=?", to)
        return True, "New leader of [%s]." % cr["tag"], mates
    if op == "open":
        db.x("UPDATE crews SET open=? WHERE id=?", 1 if a.get("open") else 0, cr["id"])
        return True, "[%s] is now %s." % (cr["tag"], "open to all" if a.get("open") else "invite-only"), mates
    if op == "rename":
        db.x("UPDATE crews SET name=? WHERE id=?", _clean(a.get("name"), 24, r"[^A-Za-z0-9_ '.-]"), cr["id"])
        return True, "Crew name changed.", mates
    return False, "Unknown crew operation.", []


def run_op(c_or_pid, op, a):
    pid = c_or_pid
    ok, text, changed = crew_op(pid, op, a)
    _gid_tag.clear()
    if ok:
        refresh_people(set(changed) | {pid})
    return ok, text


# --- the WebSocket -------------------------------------------------------------------------

def hello(c, m):
    pid = str(m.get("pid") or "").lower(); key = str(m.get("key") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", pid) or len(key) < 16:
        return "bad id"
    kh = hashlib.sha256(key.encode()).hexdigest()
    row = db.one("SELECT keyhash FROM players WHERE pid=?", pid)
    if row is not None and row["keyhash"] != kh:
        return "this player id belongs to another browser"
    try: c.gid = int(m.get("gid") or 0) & 0xFFFFFFFF
    except Exception: c.gid = 0
    b = ban_of(pid, c.ip)
    if b:
        if c.gid: blocked_gids.add((c.room, c.gid))
        return b
    c.cc = _clean(m.get("cc"), 2, r"[^A-Z]") if len(_clean(m.get("cc"), 2, r"[^A-Z]")) == 2 else ""
    c.name, c.name_note = name_check(pid, _clean(m.get("name"), 10) or "Player")
    now = time.time()
    if row is None:
        db.x("INSERT INTO players (pid, keyhash, name, cc, created, seen, ip) VALUES (?,?,?,?,?,?,?)", pid, kh, c.name, c.cc, now, now, c.ip)
    else:
        db.x("UPDATE players SET name=?, cc=?, seen=?, ip=? WHERE pid=?", c.name, c.cc, now, c.ip, pid)
    c.voice = bool(m.get("voice"))
    c.hear = m.get("hear") is not False
    c.pid = pid
    return None


def chat(c, m):
    text = _text(m.get("text"))
    if not text:
        return
    mu = mute_of(c.pid)
    if mu:
        fan([c], {"t": "sys", "text": "You are muted%s%s." % (until_text(mu["until"]), (": " + mu["reason"]) if mu["reason"] else "")}); return
    now = time.monotonic()
    c.chat_t = [t for t in c.chat_t if now - t < CHAT_WINDOW]
    if len(c.chat_t) >= CHAT_BURST:
        fan([c], {"t": "sys", "text": "Slow down: %d messages per %d seconds." % (CHAT_BURST, CHAT_WINDOW)}); return
    c.chat_t.append(now)
    ch = m.get("ch") if m.get("ch") in ("room", "crew", "near", "lobby") else "room"
    msg = {"t": "chat", "ch": ch, "text": text, "ts": int(time.time() * 1000),
           "from": {"pid": c.pid, "name": c.name, "cc": c.cc, "crew": tag_of(c.pid)}}
    if ch == "lobby":
        L = lobby_of(c.pid)
        if not L:
            fan([c], {"t": "sys", "text": "You are not in a race lobby."}); return
        fan([o for o in clients.values() if o.pid in L["members"]], msg)
        return
    if ch == "crew":
        cr, _ = crew_of(c.pid)
        if not cr:
            fan([c], {"t": "sys", "text": "You are not in a crew: create or join one in the M panel."}); return
        fan(crew_clients(cr["id"]), msg)
    elif ch == "near":
        me = _where(c)
        if not me:
            fan([c], {"t": "sys", "text": "Nearby chat works while you drive in free-roam."}); return
        out = []
        for o in in_room(c.room):
            p = _where(o)
            if o is c or (p and (p[0] - me[0]) ** 2 + (p[1] - me[1]) ** 2 <= NEAR_M ** 2):
                out.append(o)
        fan(out, msg)
    else:
        fan(in_room(c.room), msg)


VX_MAX = 600              # bytes in one voice frame (20 ms of Opus at 24 kbit/s is ~60)
VX_PER_S = 80             # frames per second per speaker (50 is real time)


def voice_frame(c, data):
    """'VX', channel (1 crew radio, 2 nearby; 0, the whole room, is refused), Opus: to the channel's audience, as 'VX', channel,
    the speaker's ghost id (u32), Opus. Muted players are dropped; the audience is worked out
    at most every 0.5 s per speaker."""
    if len(data) > VX_MAX:
        return
    now = time.monotonic()
    if now - c.vx_t >= 1.0:
        c.vx_t = now; c.vx_n = 0
    c.vx_n += 1
    if c.vx_n > VX_PER_S:
        return
    if now - c.vx_mute[0] > 2.0:
        c.vx_mute = (now, bool(mute_of(c.pid)))
    if c.vx_mute[1]:
        return
    # only Nearby (2) and Crew radio (1): voice to the whole room was taken out (owner, 2026-11-12:
    # "only do proximity or crew radio voice chat"), and an old page asking for it is refused here
    ch = data[2]
    if ch not in (1, 2):
        return
    t, lastch, aud = c.vx_aud
    if now - t > 0.5 or lastch != ch:
        if ch == 1:
            cr, _ = crew_of(c.pid)
            aud = [o for o in crew_clients(cr["id"])] if cr else []
        elif ch == 2:
            me = _where(c)
            aud = []
            if me:
                for o in in_room(c.room):
                    p = _where(o)
                    if p and (p[0] - me[0]) ** 2 + (p[1] - me[1]) ** 2 <= 210.0 ** 2:
                        aud.append(o)
        aud = [o for o in aud if o.pid != c.pid]
        c.vx_aud = (now, ch, aud)
    out = b"VX" + bytes([ch]) + struct.pack("<I", c.gid & 0xFFFFFFFF) + data[3:]
    for o in aud:
        if o.hear and not o.ws.closed:
            asyncio.ensure_future(_raw_bytes(o.ws, out))


async def _raw_bytes(ws, b):
    try:
        await ws.send_bytes(b)
    except Exception:
        pass


def rtc(c, m, kind):
    now = time.monotonic()
    if now - c.rtc_t > 10:
        c.rtc_t = now; c.rtc_n = 0
    c.rtc_n += 1
    if c.rtc_n > RTC_PER_10S:
        return
    to = str(m.get("to") or "")
    cr, _ = crew_of(c.pid)
    crew_pids = {r["pid"] for r in db.q("SELECT pid FROM members WHERE crew=?", cr["id"])} if cr else set()
    out = {"t": kind, "from": c.pid}
    if kind == "rtc":
        out["d"] = m.get("d")
    else:                                            # talk: who is talking on which channel
        if m.get("on") and mute_of(c.pid):
            fan([c], {"t": "sys", "text": "You are muted: voice is off for you."}); return
        if m.get("ch") not in ("crew", "near"):  # no room-wide voice (see voice_frame)
            return
        out["ch"] = m.get("ch")
        out["on"] = bool(m.get("on"))
    if to:                                           # one player: same room, or a crew mate anywhere
        fan([o for o in by_pid(to) if o.room == c.room or to in crew_pids], out)
    else:                                            # talk state: the room and the crew
        fan([o for o in clients.values() if o is not c and o.pid and (o.room == c.room or o.pid in crew_pids)], out)


async def ws_social(request):
    room = request.query.get("room", "").strip()[:64] or "mc3"
    if sum(1 for c in clients.values() if c.room == room) >= SOCIAL_ROOM_MAX:
        return web.Response(status=409, text="room full")
    ws = web.WebSocketResponse(max_msg_size=64 * 1024, heartbeat=30)
    await ws.prepare(request)
    c = Client(ws, room, client_ip(request))
    clients[ws] = c
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                if c.pid and len(msg.data) > 3 and msg.data[:2] == b"VX":
                    voice_frame(c, msg.data)
                continue
            if msg.type != WSMsgType.TEXT:
                continue
            if msg.data == "ping":
                await ws.send_str("pong"); continue
            try:
                m = json.loads(msg.data)
                if not isinstance(m, dict):
                    continue
            except Exception:
                continue
            t = m.get("t")
            if t == "hi":
                was = c.pid
                err = hello(c, m)
                if isinstance(err, dict):            # banned
                    await send(ws, err); await ws.close(); break
                if err:
                    await send(ws, {"t": "err", "e": err}); continue
                _gid_tag.clear()
                if c.name_note:
                    await send(ws, {"t": "name", "name": c.name, "note": c.name_note})
                await send(ws, me_msg(c.pid))
                await send(ws, friends_msg(c.pid))
                await send(ws, lobbies_msg())
                await send(ws, meets_msg(room))
                L = lobby_of(c.pid)
                if L:
                    L["members"][c.pid]["gone"] = None
                    await send(ws, lobby_msg(L))
                for r in db.q("SELECT p.*, pl.name AS fname, pl.cc AS fcc FROM pms p LEFT JOIN players pl ON pl.pid=p.frm "
                              "WHERE p.too=? AND p.delivered=0 ORDER BY p.id LIMIT 50", c.pid):
                    await send(ws, {"t": "pm", "from": {"pid": r["frm"], "name": r["fname"] or "Player", "cc": r["fcc"] or ""},
                                    "text": r["text"], "ts": int(r["t"] * 1000), "old": True})
                db.x("UPDATE pms SET delivered=1 WHERE too=? AND delivered=0", c.pid)
                if not was:
                    notify_friends(c.pid)
                await send(ws, {"t": "roster", "room": room, "players": [card(o) for o in in_room(room)]})
                fan([o for o in in_room(room) if o is not c], {"t": "upd" if was else "join", "p": card(c)})
                continue
            if not c.pid:
                await send(ws, {"t": "err", "e": "say hi first"}); continue
            if t == "chat":
                chat(c, m)
            elif t == "crew":
                ok, text = run_op(c.pid, str(m.get("op") or ""), m)
                if text:
                    await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
            elif t == "me":
                await send(ws, me_msg(c.pid))
            elif t == "friend":
                ok, text = friend_op(c, str(m.get("op") or ""), m)
                if text:
                    await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
            elif t == "pm":
                pm(c, m)
            elif t == "where":
                await send(ws, where(c, str(m.get("pid") or "")))
            elif t == "meet":
                ok, text = meet_op(c, m)
                if text:
                    await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
            elif t == "rooms":
                await send(ws, rooms_msg())
            elif t == "report":
                ok, text = report_player(c, m)
                await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
            elif t == "lobby":
                ok, text = lobby_op(c, str(m.get("op") or ""), m)
                if text:
                    await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
            elif t == "claim":
                ok, text = claim_op(c, bool(m.get("on", True)))
                await send(ws, {"t": "sys" if ok else "err", "text": text, "e": None if ok else text})
                await send(ws, me_msg(c.pid))
            elif t == "crews":
                await send(ws, {"t": "crews", "list": list_crews(str(m.get("q") or ""))})
            elif t == "hear":
                c.hear = bool(m.get("on"))
            elif t == "voice":
                c.voice = bool(m.get("on"))
                fan(in_room(room), {"t": "upd", "p": card(c)})
            elif t in ("rtc", "talk"):
                rtc(c, m, t)
    finally:
        clients.pop(ws, None)
        if c.pid:
            fan(in_room(room), {"t": "part", "pid": c.pid, "gid": c.gid})
            if not by_pid(c.pid):
                notify_friends(c.pid)
                L = lobby_of(c.pid)
                if L:                                    # 30 s to come back (a reload) before leaving it
                    L["members"][c.pid]["gone"] = time.monotonic()
            cr, _ = crew_of(c.pid)
            if cr:                                   # crew mates see who is online
                refresh_people([o.pid for o in crew_clients(cr["id"])])
    return ws


# --- friends: requests, list, private messages, where a friend is --------------------------

FRIENDS_MAX = 250
PM_KEEP = 100             # stored messages per pair (for friends who are offline)


def friend_pids(pid):
    return [r["b"] for r in db.q("SELECT b FROM friends WHERE a=?", pid)]


def friends_msg(pid):
    by = {}
    for c in clients.values():
        if c.pid and c.pid not in by:
            by[c.pid] = c
    out = []
    for r in db.q("SELECT f.b, p.name, p.cc, p.seen FROM friends f LEFT JOIN players p ON p.pid=f.b WHERE f.a=? ORDER BY lower(p.name)", pid):
        c = by.get(r["b"])
        cl = db.one("SELECT name FROM names WHERE pid=?", r["b"])
        out.append({"pid": r["b"], "name": c.name if c else (cl["name"] if cl else r["name"] or "Player"), "cc": c.cc if c else r["cc"] or "",
                    "crew": tag_of(r["b"]), "online": bool(c), "room": c.room if c else None, "gid": c.gid if c else 0,
                    "seen": r["seen"]})
    inc = [{"pid": r["frm"], "name": r["name"] or "Player", "cc": r["cc"] or ""} for r in
           db.q("SELECT q.frm, p.name, p.cc FROM freqs q LEFT JOIN players p ON p.pid=q.frm WHERE q.too=? ORDER BY q.t DESC LIMIT 50", pid)]
    outg = [{"pid": r["too"], "name": r["name"] or "Player"} for r in
            db.q("SELECT q.too, p.name FROM freqs q LEFT JOIN players p ON p.pid=q.too WHERE q.frm=? ORDER BY q.t DESC LIMIT 50", pid)]
    return {"t": "friends", "list": out, "in": inc, "out": outg, "max": FRIENDS_MAX}


def refresh_friends(*pids):
    for pid in set(pids):
        if pid:
            fan(by_pid(pid), friends_msg(pid))


def notify_friends(pid):
    """a player came online or went offline (or moved room): their friends' lists change"""
    refresh_friends(*[f for f in friend_pids(pid) if by_pid(f)])


def find_player(name):
    """a player id for a name: the one who claimed it, else the one online player using it"""
    n = _clean(name, 10)
    if not n:
        return None, "Type a name."
    r = db.one("SELECT pid FROM names WHERE namekey=?", n.lower())
    if r:
        return r["pid"], None
    on = {c.pid for c in clients.values() if c.pid and c.name.lower() == n.lower()}
    if len(on) == 1:
        return on.pop(), None
    if len(on) > 1:
        return None, "More than one player online is called %s: ask them to claim their name, or add them from the room list." % n
    return None, "No one called %s is online, and nobody has claimed that name." % n


def friend_op(c, op, a):
    me = c.pid
    if op == "add":
        to = str(a.get("pid") or "") or None
        if not to:
            to, err = find_player(str(a.get("name") or ""))
            if err:
                return False, err
        if to == me:
            return False, "That's you."
        if not db.one("SELECT 1 FROM players WHERE pid=?", to):
            return False, "No such player."
        if db.one("SELECT 1 FROM friends WHERE a=? AND b=?", me, to):
            return False, "Already friends."
        if db.one("SELECT COUNT(*) n FROM friends WHERE a=?", me)["n"] >= FRIENDS_MAX:
            return False, "Your friends list is full (%d)." % FRIENDS_MAX
        nm = (db.one("SELECT name FROM players WHERE pid=?", to) or {"name": "Player"})["name"]
        if db.one("SELECT 1 FROM freqs WHERE frm=? AND too=?", to, me):     # they asked first: friends now
            return friend_op(c, "accept", {"pid": to})
        if db.one("SELECT COUNT(*) n FROM freqs WHERE frm=?", me)["n"] >= 100:
            return False, "Too many requests waiting; wait for answers first."
        db.x("INSERT OR REPLACE INTO freqs (frm, too, t) VALUES (?,?,?)", me, to, time.time())
        refresh_friends(me, to)
        fan(by_pid(to), {"t": "sys", "text": "%s wants to be friends: answer in the M panel." % c.name})
        return True, "Friend request sent to %s." % nm
    to = str(a.get("pid") or "")
    if op == "accept":
        if not db.one("SELECT 1 FROM freqs WHERE frm=? AND too=?", to, me):
            return False, "No request from that player."
        for x, y in ((me, to), (to, me)):
            if db.one("SELECT COUNT(*) n FROM friends WHERE a=?", x)["n"] >= FRIENDS_MAX:
                return False, "A friends list is full."
        db.x("DELETE FROM freqs WHERE (frm=? AND too=?) OR (frm=? AND too=?)", to, me, me, to)
        now = time.time()
        db.x("INSERT OR IGNORE INTO friends (a, b, t) VALUES (?,?,?)", me, to, now)
        db.x("INSERT OR IGNORE INTO friends (a, b, t) VALUES (?,?,?)", to, me, now)
        refresh_friends(me, to)
        fan(by_pid(to), {"t": "sys", "text": "%s accepted: you are friends now." % c.name})
        return True, "You are friends now."
    if op in ("decline", "cancel"):
        db.x("DELETE FROM freqs WHERE (frm=? AND too=?) OR (frm=? AND too=?)", to, me, me, to)
        refresh_friends(me, to)
        return True, ""
    if op == "remove":
        db.x("DELETE FROM friends WHERE (a=? AND b=?) OR (a=? AND b=?)", me, to, to, me)
        refresh_friends(me, to)
        return True, "Removed from your friends."
    if op == "list":
        fan([c], friends_msg(me))
        return True, ""
    return False, "Unknown friends operation."


def pm(c, m):
    to = str(m.get("to") or ""); text = _text(m.get("text"))
    if not text:
        return
    if not db.one("SELECT 1 FROM friends WHERE a=? AND b=?", c.pid, to):
        fan([c], {"t": "sys", "text": "Private messages go to friends only."}); return
    mu = mute_of(c.pid)
    if mu:
        fan([c], {"t": "sys", "text": "You are muted%s." % until_text(mu["until"])}); return
    now = time.monotonic()
    c.chat_t = [t for t in c.chat_t if now - t < CHAT_WINDOW]
    if len(c.chat_t) >= CHAT_BURST:
        fan([c], {"t": "sys", "text": "Slow down: %d messages per %d seconds." % (CHAT_BURST, CHAT_WINDOW)}); return
    c.chat_t.append(now)
    msg = {"t": "pm", "from": {"pid": c.pid, "name": c.name, "cc": c.cc, "crew": tag_of(c.pid)}, "to": to,
           "text": text, "ts": int(time.time() * 1000)}
    targets = by_pid(to)
    db.x("INSERT INTO pms (frm, too, text, t, delivered) VALUES (?,?,?,?,?)", c.pid, to, text, time.time(), 1 if targets else 0)
    db.x("DELETE FROM pms WHERE id IN (SELECT id FROM pms WHERE (frm=? AND too=?) OR (frm=? AND too=?) ORDER BY id DESC LIMIT -1 OFFSET ?)",
         c.pid, to, to, c.pid, PM_KEEP)
    fan(targets + [o for o in by_pid(c.pid)], msg)
    if not targets:
        fan([c], {"t": "sys", "text": "Offline: they will get it when they next play."})


def where(c, pid):
    if not db.one("SELECT 1 FROM friends WHERE a=? AND b=?", c.pid, pid):
        return {"t": "where", "pid": pid, "error": "not a friend"}
    best = None
    for o in by_pid(pid):
        p = _where(o)
        if p or not best:
            best = (o, p)
    if not best:
        return {"t": "where", "pid": pid, "error": "offline"}
    o, p = best
    return {"t": "where", "pid": pid, "room": o.room, "gid": o.gid, "x": p[0] if p else None, "z": p[1] if p else None,
            "roam": bool(p)}


# --- race lobbies ------------------------------------------------------------------------------
# A host makes a lobby (name, optional password, who may join, 2-8 players, race settings); the
# others see the list (lobbies_msg, pushed to everyone on a change), join, ready up; the host
# starts: a countdown (start_at, relay time) goes to every member, then "racing" with the room
# the race runs in (race-<id>: its own virtual LAN, so System Link traffic stays among them).
# Driving each player's game into that race is the page's menu-drive's job (mc3menu.raceStart).
# Lobbies live in memory: a relay restart ends them. Results are kept (results table).

lobbies = {}              # id -> lobby dict
LOBBY_MAX = 8             # MC3 System Link holds 8
COUNTDOWN = 5.0
GONE_GRACE = 30.0
# Arcade's modes: a new profile has only cruise / ctf (Capture The Flag) / paint in San Diego;
# the race types unlock through Career (menu-drive session, 2026-11-11)
MODES = ("cruise", "ctf", "paint", "circuit", "ordered", "unordered", "autocross", "frenzy", "free")
CITIES = ("San Diego", "Atlanta", "Detroit", "Tokyo")


def lobby_of(pid):
    for L in lobbies.values():
        if pid in L["members"]:
            return L
    return None


def _settings(a, old=None):
    o = dict(old or {"mode": "cruise", "city": "San Diego", "track": "", "laps": 2, "traffic": False})
    # the page's choices come from the game's own Arcade rows (mc3menu.raceOptions): ids for
    # cruise / ctf / paint, the game's names for anything else -- any short clean name is taken
    md = _clean(a.get("mode"), 24, r"[^A-Za-z0-9 _'.&-]")
    if md: o["mode"] = md
    ct = _clean(a.get("city"), 24, r"[^A-Za-z0-9 _'.&-]")
    if ct: o["city"] = ct
    if "track" in a: o["track"] = _clean(a.get("track"), 32, r"[^A-Za-z0-9_ '.&-]")
    if "laps" in a:
        try: o["laps"] = max(1, min(10, int(a["laps"])))
        except Exception: pass
    if "traffic" in a: o["traffic"] = bool(a["traffic"])
    if "cls" in a and a.get("cls") in ("", "D", "C", "B", "A"): o["cls"] = a["cls"]   # car class lock ('' any)
    o.setdefault("cls", "")
    return o


def lobby_card(L):
    return {"id": L["id"], "name": L["name"], "host": L["members"][L["host"]]["name"] if L["host"] in L["members"] else "",
            "locked": bool(L["pw"]), "who": L["who"], "n": len(L["members"]), "max": L["max"], "state": L["state"],
            "settings": L["settings"]}


def lobbies_msg():
    return {"t": "lobbies", "list": [lobby_card(L) for L in lobbies.values()], "now": time.time()}


def lobby_msg(L):
    on = online_pids()
    return {"t": "lobby", "id": L["id"], "name": L["name"], "host": L["host"], "locked": bool(L["pw"]), "who": L["who"],
            "max": L["max"], "state": L["state"], "settings": L["settings"], "room": L["room"], "race": L.get("race"),
            "start_at": L.get("start_at"), "now": time.time(),
            "members": [{"pid": p, "name": m["name"], "cc": m["cc"], "crew": tag_of(p), "ready": m["ready"], "online": p in on,
                         "result": m.get("result"), "course": m.get("course"), "car": m.get("car", ""), "cls": m.get("cls", "")}
                        for p, m in L["members"].items()]}


_lobbies_dirty = False


def lobbies_changed(L=None):
    global _lobbies_dirty
    if L is not None and L["id"] in lobbies:
        fan([o for o in clients.values() if o.pid in L["members"]], lobby_msg(L))
    if not _lobbies_dirty:                       # the list, to everyone, at most every 0.3 s
        _lobbies_dirty = True
        def flush():
            global _lobbies_dirty
            _lobbies_dirty = False
            fan([o for o in clients.values() if o.pid], lobbies_msg())
        asyncio.get_event_loop().call_later(0.3, flush)


def _leave(L, pid, why=None):
    L["members"].pop(pid, None)
    fan(by_pid(pid), {"t": "lobby", "id": None})
    if why:
        fan(by_pid(pid), {"t": "sys", "text": why})
    if not L["members"]:
        lobbies.pop(L["id"], None)
    else:
        mates = [o for o in clients.values() if o.pid in L["members"]]
        if L["host"] == pid:                     # the race goes on: the longest-standing member hosts now
            L["host"] = next(iter(L["members"]))
            fan(mates, {"t": "sys", "text": "The host left: %s hosts the race now." % L["members"][L["host"]]["name"]})
        if L["state"] == "countdown" and len(L["members"]) < 2:
            L["state"] = "open"; L.pop("start_at", None)
        if L["state"] == "racing" and all(m.get("result") for m in L["members"].values()):
            rank_race(L)                         # everyone left in it has finished
    lobbies_changed(L)


def rank_race(L):
    for i, (p, m) in enumerate(sorted(L["members"].items(), key=lambda x: x[1]["result"]["ms"])):
        m["result"]["rank"] = i + 1
    fan([o for o in clients.values() if o.pid in L["members"]], {"t": "results", "id": L["id"], "race": L["race"],
         "list": sorted([{"pid": p, "name": m["name"], **m["result"]} for p, m in L["members"].items()], key=lambda r: r["rank"])})
    L["state"] = "open"
    for m in L["members"].values(): m["ready"] = False


def lobby_op(c, op, a):
    me = c.pid
    L = lobby_of(me)
    if op == "list":
        fan([c], lobbies_msg()); return True, ""
    if op == "create":
        if L:
            return False, "Leave your lobby first."
        name = _text(a.get("name"))[:28] or (c.name + "'s race")
        who = a.get("who") if a.get("who") in ("all", "friends", "crew") else "all"
        try: mx = max(2, min(LOBBY_MAX, int(a.get("max") or LOBBY_MAX)))
        except Exception: mx = LOBBY_MAX
        pw = str(a.get("password") or "")[:32]
        lid = hashlib.sha256(os.urandom(16)).hexdigest()[:6]
        L = {"id": lid, "name": name, "host": me, "pw": hashlib.sha256(pw.encode()).hexdigest() if pw else "",
             "who": who, "max": mx, "state": "open", "settings": _settings(a), "room": "race-" + lid,
             "members": {me: {"name": c.name, "cc": c.cc, "ready": False, "gone": None}}, "t": time.time()}
        lobbies[lid] = L
        lobbies_changed(L)
        return True, "Race lobby \"%s\" made. Others can join from the RACES list." % name
    if op == "join":
        T = lobbies.get(str(a.get("id") or ""))
        if not T:
            return False, "That race lobby is gone."
        if L and L is T:
            return False, ""
        if L:
            return False, "Leave your lobby first."
        if T["state"] != "open":
            return False, "That race has started."
        if len(T["members"]) >= T["max"]:
            return False, "That race lobby is full."
        if T["pw"] and hashlib.sha256(str(a.get("password") or "").encode()).hexdigest() != T["pw"]:
            return False, "Wrong password."
        if T["who"] == "friends" and not db.one("SELECT 1 FROM friends WHERE a=? AND b=?", T["host"], me):
            return False, "Only the host's friends can join that one."
        if T["who"] == "crew":
            hc, _ = crew_of(T["host"]); mc, _ = crew_of(me)
            if not hc or not mc or hc["id"] != mc["id"]:
                return False, "Only the host's crew can join that one."
        T["members"][me] = {"name": c.name, "cc": c.cc, "ready": False, "gone": None}
        lobbies_changed(T)
        return True, ""
    if not L:
        return False, "You are not in a race lobby."
    if op == "leave":
        _leave(L, me); return True, "You left the race lobby."
    if op == "car":                               # the car this member drives, and its class (the page reads it)
        m = L["members"][me]
        car = _clean(a.get("car"), 16, r"[^A-Za-z0-9 _.'-]"); cls = a.get("cls") if a.get("cls") in ("D", "C", "B", "A") else ""
        if (m.get("car"), m.get("cls")) != (car, cls):
            m["car"], m["cls"] = car, cls
            lk = L["settings"].get("cls")
            if lk and cls and cls != lk and m["ready"]:
                m["ready"] = False
            lobbies_changed(L)
        return True, ""
    if op == "ready":
        if L["state"] != "open":
            return False, ""
        lk, mine = L["settings"].get("cls"), L["members"][me].get("cls", "")
        if a.get("on", True) and lk and mine and mine != lk:
            return False, "This race is for class %s cars; yours is class %s. Change car first." % (lk, mine)
        L["members"][me]["ready"] = bool(a.get("on", True)); lobbies_changed(L); return True, ""
    if op == "course":                            # what the menu drive put this player's game into
        if L["state"] not in ("countdown", "racing"):
            return False, ""
        L["members"][me]["course"] = {"same": bool(a.get("same")), "check": _clean(a.get("check"), 64, r"[^A-Za-z0-9_:.-]")}
        lobbies_changed(L); return True, ""
    if op == "result":                            # a finished race: time (ms), position (from the game)
        if L["state"] != "racing":
            return False, "No race running."
        try: ms = int(a.get("ms")); pos = int(a.get("pos") or 0)
        except Exception: return False, "Bad result."
        if not (1000 <= ms <= 3600_000):
            return False, "Bad result."
        st = L["settings"]
        L["members"][me]["result"] = {"ms": ms, "pos": pos}
        db.x("INSERT OR REPLACE INTO results (race, pid, name, mode, city, track, laps, ms, pos, car, t) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
             L["race"], me, c.name, st["mode"], st["city"], st["track"], st["laps"], ms, pos, _clean(a.get("car"), 16, r"[^A-Za-z0-9 _.'-]"), time.time())
        done = [m for m in L["members"].values() if m.get("result")]
        if len(done) == len(L["members"]):        # everyone in: ranked by time, back to the lobby
            rank_race(L)
        lobbies_changed(L)
        return True, ""
    if L["host"] != me:
        return False, "Only the host can do that."
    if op == "settings":
        if L["state"] != "open":
            return False, ""
        L["settings"] = _settings(a, L["settings"])
        if "name" in a: L["name"] = _text(a.get("name"))[:28] or L["name"]
        if a.get("who") in ("all", "friends", "crew"): L["who"] = a["who"]
        if "password" in a: L["pw"] = hashlib.sha256(str(a["password"]).encode()).hexdigest() if a.get("password") else ""
        for m in L["members"].values(): m["ready"] = False   # new settings: everyone ready again
        lobbies_changed(L); return True, ""
    if op == "kick":
        to = str(a.get("pid") or "")
        if to == me or to not in L["members"]:
            return False, ""
        _leave(L, to, "The host took you out of the race lobby."); return True, ""
    if op == "start":
        if L["state"] != "open":
            return False, ""
        if len(L["members"]) < 2:
            return False, "A race needs at least 2 players."
        if not all(m["ready"] for p, m in L["members"].items() if p != me):
            return False, "Not everyone is ready."
        L["state"] = "countdown"; L["start_at"] = time.time() + COUNTDOWN
        for m in L["members"].values(): m.pop("course", None); m.pop("result", None)
        L["race"] = L["id"] + "-" + str(int(time.time()))
        lobbies_changed(L)
        def go(lid=L["id"], race=L["race"]):
            T = lobbies.get(lid)
            if T and T["state"] == "countdown" and T.get("race") == race:
                T["state"] = "racing"; lobbies_changed(T)
        asyncio.get_event_loop().call_later(COUNTDOWN, go)
        return True, ""
    if op == "cancel":                            # back to the lobby (a countdown or a race nobody finished)
        L["state"] = "open"; L.pop("start_at", None)
        for m in L["members"].values(): m["ready"] = False; m.pop("result", None)
        lobbies_changed(L); return True, ""
    return False, "Unknown lobby operation."


async def lobby_sweeper():
    while True:
        await asyncio.sleep(5)
        t = time.time()
        for room, L in list(meets.items()):           # meet-ups past their time: gone for everyone
            if any(m["until"] <= t for m in L):
                L[:] = [m for m in L if m["until"] > t]
                fan(in_room(room), meets_msg(room))
            if not L:
                meets.pop(room, None)
        now = time.monotonic()
        for L in list(lobbies.values()):
            for p, m in list(L["members"].items()):
                if m.get("gone") and now - m["gone"] > GONE_GRACE and not by_pid(p):
                    _leave(L, p)


async def http_leaderboard(request):
    """GET /leaderboard?mode=&city=&track=&laps=  best time per player (top 50); no filter: the
    tracks raced, with how many results each"""
    q = request.query
    if not any(k in q for k in ("mode", "city", "track", "laps")):
        rows = db.q("SELECT mode, city, track, laps, COUNT(*) n, MIN(ms) best FROM results GROUP BY mode, city, track, laps ORDER BY n DESC LIMIT 100")
        return web.json_response([dict(r) for r in rows], headers=CORS)
    rows = db.q("SELECT pid, name, MIN(ms) ms, car, t FROM results WHERE mode=? AND city=? AND track=? AND laps=? GROUP BY pid ORDER BY ms LIMIT 50",
                q.get("mode", "cruise"), q.get("city", "San Diego"), q.get("track", ""), int(q.get("laps", 2) or 2))
    return web.json_response([{"rank": i + 1, "name": r["name"], "ms": r["ms"], "car": r["car"], "t": r["t"]} for i, r in enumerate(rows)], headers=CORS)


# --- meet-ups: "meet at <place> at <time>", for everyone in the room, until it expires --------

meets = {}                # room -> [ {id, pid, name, place, x, z, at, until} ]
MEET_KEEP = 15 * 60       # shown until this long after the time


def meets_msg(room):
    now = time.time()
    return {"t": "meets", "list": [dict(m) for m in meets.get(room, []) if m["until"] > now], "now": now}


def meet_op(c, a):
    op = a.get("op") or "post"
    L = meets.setdefault(c.room, [])
    if op == "cancel":
        n = len(L); L[:] = [m for m in L if not (m["id"] == a.get("id") and m["pid"] == c.pid)]
        if len(L) != n:
            fan(in_room(c.room), meets_msg(c.room))
        return True, ""
    if mute_of(c.pid):
        return False, "You are muted."
    place = _text(a.get("place"))[:60]
    if not place:
        return False, "Say where to meet."
    try: mins = max(0, min(180, int(a.get("mins") or 0)))
    except Exception: mins = 0
    now = time.time()
    L[:] = [m for m in L if m["until"] > now]
    if sum(1 for m in L if m["pid"] == c.pid) >= 3 or len(L) >= 20:
        return False, "Too many meet-ups posted; cancel one first."
    try: x, z = float(a["x"]), float(a["z"])
    except Exception:
        p = _where(c); x, z = (p[0], p[1]) if p else (None, None)
    m = {"id": hashlib.sha256(os.urandom(8)).hexdigest()[:6], "pid": c.pid, "name": c.name, "place": place,
         "x": x, "z": z, "at": now + mins * 60, "until": now + mins * 60 + MEET_KEEP}
    L.append(m)
    fan(in_room(c.room), meets_msg(c.room))
    fan(in_room(c.room), {"t": "meet", "m": m})
    return True, ""


def rooms_msg():
    """the free-roam rooms in use (race rooms left out), with how many are in each"""
    n = {}
    for c in clients.values():
        if c.pid and not c.room.startswith("race-"):
            n[c.room] = n.get(c.room, 0) + 1
    return {"t": "rooms", "list": sorted([{"id": r, "n": k} for r, k in n.items()], key=lambda x: (-x["n"], x["id"]))}


# --- reports about a player (the owner reads them: /admin/reports, admin.py reports) -----------

REPORT_WHY = ("cheating", "abuse", "spam", "griefing", "name", "other")
_report_t = {}


def report_player(c, m):
    to = str(m.get("pid") or "")
    if to == c.pid:
        return False, "That's you."
    row = db.one("SELECT name FROM players WHERE pid=?", to)
    if not row:
        return False, "No such player."
    now = time.time()
    q = [t for t in _report_t.get(c.pid, []) if now - t < 3600]
    if len(q) >= 6:
        return False, "You have sent a lot of reports this hour; the host will read them."
    q.append(now); _report_t[c.pid] = q
    why = m.get("why") if m.get("why") in REPORT_WHY else "other"
    tr = []
    for o in by_pid(to):                         # where they were, the last ~20 s (their room)
        tr = list(trail.get((o.room, o.gid), []))
        if tr: break
    db.x("INSERT INTO reports (t, frm, frm_name, about, about_name, room, why, text, trail) VALUES (?,?,?,?,?,?,?,?,?)",
         now, c.pid, c.name, to, row["name"], c.room, why, _text(m.get("text"))[:200], json.dumps(tr))
    return True, "Report sent. Thanks: the host reads them."


def reports_html(rows):
    esc = lambda x: str(x if x is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h = ["<!doctype html><meta charset=utf-8><title>MC3 reports</title><style>body{font:14px system-ui;background:#111;color:#ddd;margin:20px}"
         "td,th{padding:4px 8px;border-bottom:1px solid #333;vertical-align:top;text-align:left}th{color:#fc6}code{color:#9cf}</style>",
         "<h2>Player reports (newest first)</h2><p>Ban: <code>python relay/admin.py ban &lt;player id&gt; \"reason\"</code></p><table>",
         "<tr><th>#</th><th>when</th><th>about</th><th>why</th><th>what they said</th><th>from</th><th>room</th><th>last positions</th></tr>"]
    for r in rows:
        tr = json.loads(r["trail"] or "[]")
        moves = " ".join("%.0f,%.0f" % (p[1], p[2]) for p in tr[-8:])
        h.append("<tr><td>%d</td><td>%s</td><td><b>%s</b><br><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            r["id"], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["t"])), esc(r["about_name"]), esc(r["about"]), esc(r["why"]),
            esc(r["text"]), esc(r["frm_name"]), esc(r["room"]), esc(moves) or "-"))
    h.append("</table>")
    return "".join(h)


# --- claimed names, bans, mutes ---------------------------------------------------------------

NAME_MIN = 3
GUEST_RX = re.compile(r"^(player|p-|guest)", re.I)


def client_ip(request):
    return (request.headers.get("Cf-Connecting-Ip") or request.remote or "").strip()[:64]


def _local_ip(ip):
    return ip in ("", "127.0.0.1", "::1", "localhost") or ip.startswith(("172.", "10.", "192.168."))


def until_text(until):
    if not until:
        return ""
    return " until " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(until))


def ban_of(pid, ip=""):
    """the ban that applies to this player (by id, or by address if the ban has one), as the
    message the page shows, else None"""
    now = time.time()
    r = db.one("SELECT * FROM bans WHERE lifted IS NULL AND (until IS NULL OR until > ?) AND (pid=? OR (ip != '' AND ip=?)) "
               "ORDER BY n DESC LIMIT 1", now, pid, ip or "-")
    if not r:
        return None
    return {"t": "banned", "n": r["n"], "reason": r["reason"] or "", "until": r["until"]}


def ip_banned(ip):
    """a ban that names this address (bans by address are only made on request: shared networks)"""
    if not ip or _local_ip(ip):
        return False
    return bool(db.one("SELECT 1 FROM bans WHERE lifted IS NULL AND (until IS NULL OR until > ?) AND ip=?", time.time(), ip))


def mute_of(pid):
    r = db.one("SELECT * FROM mutes WHERE pid=?", pid)
    if r and (r["until"] is None or r["until"] > time.time()):
        return r
    return None


def name_check(pid, name):
    """the name this player may use: their own claim, an unclaimed name, or (when someone else
    claimed it) a stand-in -- with a note for the page"""
    r = db.one("SELECT pid, name FROM names WHERE namekey=?", name.lower())
    if r and r["pid"] != pid:
        mine = db.one("SELECT name FROM names WHERE pid=?", pid)
        if mine:
            return mine["name"], "%s is another player's claimed name; you are %s (your claimed name)." % (name, mine["name"])
        stand = ("P-" + pid[:4]).upper()[:10]
        return stand, "%s is another player's claimed name; you show as %s until you pick another name." % (name, stand)
    return name, None


def claim_op(c, on):
    if not on:
        db.x("DELETE FROM names WHERE pid=?", c.pid)
        return True, "You let go of your claimed name."
    n = c.name
    if len(n) < NAME_MIN or GUEST_RX.match(n):
        return False, "Pick a name of your own (3-10 letters, not Player...) before claiming it."
    r = db.one("SELECT pid FROM names WHERE namekey=?", n.lower())
    if r and r["pid"] != c.pid:
        return False, "%s is already claimed." % n
    db.x("DELETE FROM names WHERE pid=?", c.pid)
    db.x("INSERT INTO names (namekey, name, pid, t) VALUES (?,?,?,?)", n.lower(), n, c.pid, time.time())
    return True, "The name %s is yours now: nobody else can use it." % n


def kick(pid, msg):
    for o in by_pid(pid):
        if o.gid:
            blocked_gids.add((o.room, o.gid))
        fan([o], msg)
        asyncio.get_event_loop().call_later(0.3, lambda w=o.ws: asyncio.ensure_future(w.close()))
    _gid_tag.clear()


# --- admin: local only (never through the tunnel); relay/admin.py drives it ----------------------

def _admin_ok(request):
    if request.headers.get("Cf-Connecting-Ip") or request.headers.get("Cf-Ray"):
        return False
    return (request.remote or "") in ("127.0.0.1", "::1")


def _player_row(r):
    on = online_pids()
    cl = db.one("SELECT name FROM names WHERE pid=?", r["pid"])
    return {"pid": r["pid"], "name": r["name"], "cc": r["cc"], "claimed": cl["name"] if cl else None,
            "seen": r["seen"], "online": r["pid"] in on, "crew": tag_of(r["pid"]),
            "ban": ban_of(r["pid"]), "muted": bool(mute_of(r["pid"]))}


async def admin(request):
    if not _admin_ok(request):
        return web.Response(status=403, text="admin is local only")
    act = request.match_info["act"]
    a = dict(request.query)
    if request.method == "POST":
        try: a.update(await request.json())
        except Exception: pass
    now = time.time()
    pid = str(a.get("pid") or "").lower()
    if act == "find":
        q = str(a.get("q") or "").lower()
        rows = db.q("SELECT * FROM players WHERE lower(name) LIKE ? OR pid LIKE ? OR pid IN "
                    "(SELECT pid FROM names WHERE namekey LIKE ?) ORDER BY seen DESC LIMIT 30", "%" + q + "%", q + "%", "%" + q + "%")
        return web.json_response([_player_row(r) for r in rows])
    if act == "who":                              # diagnosis: each social client's ghost id and position
        now = time.monotonic()
        out = []
        for c in clients.values():
            p = pos.get((c.room, c.gid))
            out.append({"name": c.name, "pid": (c.pid or "")[:8], "room": c.room, "gid": c.gid, "hear": c.hear, "voice": c.voice,
                        "pos_age": round(now - p[2], 1) if p else None})
        frames = {}
        for (room, g), p in pos.items():
            if now - p[2] < 10: frames.setdefault(room, []).append(g)
        return web.json_response({"clients": out, "ghosts_sending": frames})
    if act == "reports":
        rows = db.q("SELECT * FROM reports ORDER BY id DESC LIMIT 200")
        if a.get("html") or "text/html" in request.headers.get("Accept", ""):
            return web.Response(text=reports_html(rows), content_type="text/html")
        return web.json_response([dict(r, trail=json.loads(r["trail"] or "[]")) for r in rows])
    if act == "bans":
        return web.json_response([dict(r) for r in db.q("SELECT * FROM bans ORDER BY n DESC LIMIT 100")])
    if act == "unban":
        if a.get("n"):
            db.x("UPDATE bans SET lifted=? WHERE n=?", now, int(a["n"]))
        else:
            db.x("UPDATE bans SET lifted=? WHERE pid=? AND lifted IS NULL", now, pid)
        blocked_gids.clear()
        return web.json_response({"ok": True})
    if act == "unclaim":
        db.x("DELETE FROM names WHERE namekey=?", str(a.get("name") or "").lower())
        return web.json_response({"ok": True})
    row = db.one("SELECT * FROM players WHERE pid=?", pid)
    if not row:
        return web.json_response({"ok": False, "text": "no such player id"}, status=404)
    if act == "ban":
        days = float(a.get("days") or 0)
        ip = row["ip"] if a.get("ip") and not _local_ip(row["ip"] or "") else ""
        cur = db.x("INSERT INTO bans (pid, ip, reason, until, t) VALUES (?,?,?,?,?)", pid, ip,
                   str(a.get("reason") or "")[:200], now + days * 86400 if days > 0 else None, now)
        kick(pid, ban_of(pid))
        return web.json_response({"ok": True, "n": cur.lastrowid, "ip": ip or None})
    if act == "mute":
        mins = float(a.get("minutes") or 0)
        until = now + mins * 60 if mins > 0 else None
        db.x("INSERT OR REPLACE INTO mutes (pid, until, reason, t) VALUES (?,?,?,?)", pid, until, str(a.get("reason") or "")[:200], now)
        for o in by_pid(pid):
            fan([o], {"t": "sys", "text": "You are muted%s%s." % (until_text(until), (": " + a["reason"]) if a.get("reason") else "")})
        return web.json_response({"ok": True})
    if act == "unmute":
        db.x("DELETE FROM mutes WHERE pid=?", pid)
        return web.json_response({"ok": True})
    return web.json_response({"ok": False, "text": "unknown action"}, status=400)


# --- HTTP ------------------------------------------------------------------------------------

def list_crews(q=""):
    on = online_pids()
    rows = db.q("SELECT c.*, (SELECT COUNT(*) FROM members m WHERE m.crew=c.id) AS n FROM crews c "
                "WHERE c.tagkey LIKE ? OR lower(c.name) LIKE ? ORDER BY n DESC, c.created LIMIT 50",
                "%" + q.lower() + "%", "%" + q.lower() + "%")
    out = []
    for r in rows:
        pids = [x["pid"] for x in db.q("SELECT pid FROM members WHERE crew=?", r["id"])]
        out.append({"tag": r["tag"], "name": r["name"], "open": bool(r["open"]), "members": r["n"],
                    "online": sum(1 for p in pids if p in on)})
    return out


CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store", "Cross-Origin-Resource-Policy": "cross-origin"}


_online_cache = {"t": 0.0, "body": None}
lan_listeners = lambda: 0      # set by relay.py: players on the game sockets (bots not counted)


async def http_online(request):
    """GET /online: how many are playing right now, for the website. Public, cached 2 s."""
    now = time.monotonic()
    if _online_cache["body"] is None or now - _online_cache["t"] > 2.0:
        pids = {c.pid for c in clients.values() if c.pid}
        roaming = {c.pid for c in clients.values() if c.pid and _where(c)}
        _online_cache["body"] = {"online": max(len(pids), lan_listeners()), "roaming": len(roaming),
                                 "races": sum(1 for L in lobbies.values() if L["state"] == "racing"),
                                 "lobbies": len(lobbies), "t": int(time.time())}
        _online_cache["t"] = now
    return web.json_response(_online_cache["body"], headers=dict(CORS, **{"Cache-Control": "public, max-age=5"}))


async def http_crews(request):
    return web.json_response(list_crews(request.query.get("q", "")[:20]), headers=CORS)


async def http_crew(request):
    cr = db.one("SELECT * FROM crews WHERE tagkey=?", request.match_info["tag"].lower()[:10])
    if not cr:
        return web.json_response({"error": "no such crew"}, status=404, headers=CORS)
    return web.json_response(crew_info(cr), headers=CORS)


async def http_crew_post(request):
    try:
        m = await request.json()
        pid = str(m.get("pid") or "").lower()
        row = db.one("SELECT keyhash FROM players WHERE pid=?", pid)
        if not row or row["keyhash"] != hashlib.sha256(str(m.get("key") or "").encode()).hexdigest():
            return web.json_response({"ok": False, "text": "unknown player"}, status=403, headers=CORS)
        ok, text = run_op(pid, str(m.get("op") or ""), m)
        return web.json_response({"ok": ok, "text": text, "me": me_msg(pid)}, headers=CORS)
    except Exception as e:
        return web.json_response({"ok": False, "text": str(e)}, status=400, headers=CORS)


async def http_options(request):
    return web.Response(headers=dict(CORS, **{"Access-Control-Allow-Methods": "GET, POST, OPTIONS"}))


def install(app):
    global db
    db = DB(_db_path())
    app.router.add_get("/social", ws_social)
    app.router.add_get("/crews", http_crews)
    app.router.add_get("/online", http_online)
    app.router.add_get("/leaderboard", http_leaderboard)
    async def _start_sweeper(app):
        app["lobby_sweeper"] = asyncio.ensure_future(lobby_sweeper())
    app.on_startup.append(_start_sweeper)
    app.router.add_get("/crew/{tag}", http_crew)
    app.router.add_post("/crew", http_crew_post)
    app.router.add_route("OPTIONS", "/crew", http_options)
    app.router.add_route("*", "/admin/{act}", admin)
    import cloud, tempfile                      # cloud saves (cloud.py), kept beside the database
    dp = _db_path()
    cloud.install(app, tempfile.mkdtemp(prefix="mc3cloud") if dp == ":memory:" else os.path.dirname(os.path.abspath(dp)))

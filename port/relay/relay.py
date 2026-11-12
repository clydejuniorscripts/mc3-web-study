"""relay.py — multiplayer relay for the MC3 web port (local / testing build).

A game-agnostic binary WebSocket forwarder. It knows nothing about Midnight Club;
it just moves bytes between players in the same room. No game code and no game
data ever touch it (PORT_PLAN.md s4).

Endpoints
  WS  /lan?room=<id>&name=<n>   System Link: forward each binary frame to the
                               other members of the room (the game's own UDP
                               lobby/race packets, tunnelled).
  WS  /roam?room=<id>&name=<n>  Free-roam ghosts: same forwarding, used for the
                               ~20 Hz car-position snapshots.
  GET /players[?rooms=a,b]      { players, online, roam, full, queue, roamBusy,
                               rooms: [{id,count,full,kind}] }  (cached ~1 s)
  GET /rooms                    [{ id, count, full, kind }]
  GET /                         health text

Limits: 64 players/room (MC3_MAX_ROOM), 64 KB/frame, per-socket rate
cap. Anti-abuse is coarse on purpose — the relay can't see the game, so this is
casual-grade (PORT_PLAN.md s4). Run:  python relay.py [--port 8099] [--host 0.0.0.0]
"""
import argparse, asyncio, math, os, struct, time, json
from collections import defaultdict, deque
from aiohttp import web, WSMsgType
import social              # identity, crews, chat, voice signalling (social.py)

# Players per room. Was 8 (MC3's System Link lobby); free-roam is one shared city, so a room
# now holds a few dozen (2026-11-11). The page draws the 16 nearest on the game's minimap and
# gives cars to the 8 nearest (minimap_ghosts.inc.c), so more players cost only bandwidth:
# each one receives everyone's ~20 frames/s of ~71 bytes (64 players: ~90 KB/s down each).
MAX_ROOM = int(os.environ.get("MC3_MAX_ROOM", 64))
GHST = b"GHST"
CREW_AT, CREW_LEN = 37, 10 # the crew name in a position frame (web/index.html mc3ghost)
NAME_AT, NAME_LEN = 25, 10 # the player's name in it
MAX_FRAME = 64 * 1024      # bytes per message
RATE_BYTES = 1_000_000     # per-socket bytes/sec ceiling (>> the ~24 KB/s expected)
RATE_MSGS = 400            # per-socket messages/sec ceiling
IDLE_SECS = 90             # drop a socket that sends nothing for this long
OUT_QUEUE = 48             # frames waiting for one slow player; beyond that the oldest go
OUT_QUEUE_BATCH = 2048     # ... for a player taking batches (batch=1): 20 ms of 200 players is ~60
BATCH_SECS = 0.02          # batch=1: frames gathered this long go out as one message
ALLOWED_ORIGINS = set()    # empty = allow any (dev); --origins to restrict (prod)

rooms = defaultdict(dict)  # room_id -> { ws: member }
_players_cache = {"t": 0.0, "body": None}


class Member:
    # out: this player's own queue of frames to send, drained by its own writer task, so a
    # slow player (a poor connection, a busy tab) only ever delays itself. Forwarding used to
    # await each peer in turn: one slow reader held up every sender in the room (measured
    # 2026-11-11: a page's 15 frames/s arrived at 1/s, with 3 s stalls for everyone).
    __slots__ = ("name", "kind", "joined", "win_t", "win_bytes", "win_msgs", "last", "out", "dropped", "listen", "batch",
                 "px", "pz", "pt", "fast_since", "mute_until", "flags")
    def __init__(self, name, kind):
        self.out = asyncio.Queue(); self.dropped = 0; self.listen = True; self.batch = False
        self.px = self.pz = None; self.pt = 0.0; self.fast_since = 0.0; self.mute_until = 0.0; self.flags = 0
        now = time.monotonic()
        self.name = name; self.kind = kind; self.joined = now
        self.win_t = now; self.win_bytes = 0; self.win_msgs = 0; self.last = now

    def allow(self, n):
        now = time.monotonic()
        if now - self.win_t >= 1.0:
            self.win_t = now; self.win_bytes = 0; self.win_msgs = 0
        self.win_bytes += n; self.win_msgs += 1; self.last = now
        return self.win_bytes <= RATE_BYTES and self.win_msgs <= RATE_MSGS


# Anti-cheat, the simple kind (owner, 2026-11-11, from the nfsu2.xyz forum: "Corolla doing 500 km/h"):
# the relay sees every position, so it measures each player's speed between frames. One jump is fine
# (a respawn, a teleport to a friend); going faster than CHEAT_SPEED units/s for CHEAT_SECS straight is
# not something the game's cars do (top speeds are ~90-110 units/s with nitro), so that player's
# position frames are not passed on for CHEAT_MUTE seconds and it is logged: /dev/cheats.
CHEAT_SPEED = 160.0
CHEAT_SECS = 1.5
CHEAT_MUTE = 10.0
JUMP = 400.0               # one move this long is a teleport/respawn, not speed
cheats = deque(maxlen=200)


def cheat_check(me, room_id, data, now):
    """True if this position frame may go on."""
    try:
        gid, x, _y, z = struct.unpack_from("<Ifff", data, 5)
    except struct.error:
        return True
    if not (math.isfinite(x) and math.isfinite(z)):
        return False
    if now < me.mute_until:
        me.px, me.pz, me.pt = x, z, now
        return False
    ok = True
    if me.px is not None and now > me.pt:
        d = math.hypot(x - me.px, z - me.pz); dt = now - me.pt
        if d < JUMP and dt < 1.0 and d / dt > CHEAT_SPEED:
            if not me.fast_since: me.fast_since = now
            elif now - me.fast_since >= CHEAT_SECS:
                me.flags += 1; me.mute_until = now + CHEAT_MUTE; me.fast_since = 0.0; ok = False
                cheats.append({"t": time.time(), "room": room_id, "gid": gid, "name": me.name,
                               "speed": round(d / dt), "flags": me.flags})
                print(f"[CHEAT] {room_id} gid {gid:08x} ({me.name}) at {d / dt:.0f} u/s for {CHEAT_SECS}s: muted {CHEAT_MUTE:.0f}s (#{me.flags})", flush=True)
        else:
            me.fast_since = 0.0
    me.px, me.pz, me.pt = x, z, now
    return ok


async def dev_cheats(request):
    return web.json_response(list(cheats))


async def ws_relay(request, kind):
    room_id = request.query.get("room", "").strip()[:64]
    name = request.query.get("name", "").strip()[:24] or "player"
    if not room_id:
        return web.Response(status=400, text="room required")
    if ALLOWED_ORIGINS and request.headers.get("Origin", "") not in ALLOWED_ORIGINS:
        return web.Response(status=403, text="origin not allowed")
    # listen=0: a sender only (test bots, bots.py): nothing is forwarded to it, and it takes
    # no place in the room -- 200 of them can stress the players without filling the room
    # or being sent each other's 600,000 frames a second. It is not counted in /players.
    if social.ip_banned(social.client_ip(request)):
        return web.Response(status=403, text="banned")
    listen = request.query.get("listen", "1") != "0"
    room = rooms[room_id]
    if listen and _listeners(room) >= MAX_ROOM:
        return web.Response(status=409, text="room full")

    ws = web.WebSocketResponse(max_msg_size=MAX_FRAME + 1024, heartbeat=30)
    await ws.prepare(request)
    me = Member(name, kind)
    me.listen = listen
    me.batch = request.query.get("batch") == "1"
    room[ws] = me

    async def writer():                  # this player's frames go out here, one at a time
        while True:
            data = await me.out.get()
            if data is None or ws.closed:
                return
            if me.batch:
                # batch=1: whatever arrives within BATCH_SECS goes out as ONE message, 'GBAT'
                # then (u16 length, frame) each. With 200 players a page got ~2,750 messages a
                # second, and handling each as its own browser event starved its main thread
                # (3.5 page frames a second, 2026-11-11); batched it is ~50.
                await asyncio.sleep(BATCH_SECS)
                parts, stop = [data], False
                while not me.out.empty() and sum(len(p) + 2 for p in parts) < MAX_FRAME:
                    d = me.out.get_nowait()
                    if d is None:
                        stop = True; break
                    parts.append(d)
                if len(parts) > 1:
                    data = b"GBAT" + b"".join(len(p).to_bytes(2, "little") + p for p in parts)
                if stop:
                    try: await ws.send_bytes(data)
                    except Exception: pass
                    return
            try:
                await ws.send_bytes(data)
            except Exception:
                return
    wtask = asyncio.ensure_future(writer())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                data = msg.data
                if len(data) > MAX_FRAME:
                    continue
                if not me.allow(len(data)):
                    continue  # over the rate cap: drop this frame
                if len(data) >= 25 and data[:4] == GHST:
                    # a position frame: note where this player is (nearby chat), and make the
                    # crew it shows the player's real crew (social.py), not whatever was typed
                    gid, x, _y, z = struct.unpack_from("<Ifff", data, 5)
                    if social.blocked(room_id, gid):        # a banned player
                        break
                    social.note_pos(room_id, gid, x, z)
                    if me.listen and not cheat_check(me, room_id, data, time.monotonic()):
                        continue    # impossible speed: not passed on for a while (/dev/cheats)
                    if me.listen and len(data) >= CREW_AT + CREW_LEN:
                        # name (a claimed name is only its owner's) and crew, as the relay knows
                        # them; a ghost with no verified player behind it shows no crew
                        ident = social.ghost_ident(room_id, gid)
                        cb = (ident[1] if ident else "").encode("ascii", "ignore")[:CREW_LEN].ljust(CREW_LEN, bytes(1))
                        if ident:
                            nb = ident[0].encode("ascii", "ignore")[:NAME_LEN].ljust(NAME_LEN, bytes(1))
                            data = data[:NAME_AT] + nb + data[NAME_AT + NAME_LEN:CREW_AT] + cb + data[CREW_AT + CREW_LEN:]
                        elif data[CREW_AT:CREW_AT + CREW_LEN] != cb:
                            data = data[:CREW_AT] + cb + data[CREW_AT + CREW_LEN:]
                for peer, m in list(room.items()):
                    if peer is ws or peer.closed or not m.listen:
                        continue
                    q = m.out
                    cap = OUT_QUEUE_BATCH if m.batch else OUT_QUEUE   # a batching player holds a window's worth
                    while q.qsize() >= cap:         # that player is behind: its oldest frames go
                        try: q.get_nowait(); m.dropped += 1
                        except asyncio.QueueEmpty: break
                    q.put_nowait(data)
            elif msg.type == WSMsgType.TEXT and msg.data == "ping":
                await ws.send_str("pong")
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        me.out.put_nowait(None)
        wtask.cancel()
        room.pop(ws, None)
        if not room:
            rooms.pop(room_id, None)
    return ws


async def lan(request):  return await ws_relay(request, "lan")
async def roam(request): return await ws_relay(request, "roam")


def _listeners(room):
    """Members that take a place (players), not send-only test bots."""
    return sum(1 for m in room.values() if m.listen)


def _counts():
    total = sum(_listeners(r) for r in rooms.values())
    roam_players = sum(_listeners(r) for r in rooms.values()
                       if any(m.kind == "roam" for m in r.values()))
    rlist = [{"id": rid, "count": _listeners(r), "full": _listeners(r) >= MAX_ROOM,
              "bots": len(r) - _listeners(r),
              "kind": next(iter(r.values())).kind if r else "lan"}
             for rid, r in rooms.items()]
    return {
        "players": total,
        "online": total,
        "roam": roam_players,
        "bots": sum(len(r) - _listeners(r) for r in rooms.values()),
        "full": sum(1 for r in rooms.values() if _listeners(r) >= MAX_ROOM),
        "queue": 0,
        "roamBusy": roam_players >= MAX_ROOM,
        "rooms": rlist,
    }


async def players(request):
    now = time.monotonic()
    if _players_cache["body"] is None or now - _players_cache["t"] > 1.0:
        _players_cache["body"] = _counts(); _players_cache["t"] = now
    body = dict(_players_cache["body"])
    want = request.query.get("rooms")
    if want:
        ids = set(want.split(","))
        body = dict(body)
        body["rooms"] = [r for r in body["rooms"] if r["id"] in ids]
    return web.json_response(body, headers={"Access-Control-Allow-Origin": "*",
                                            "Cache-Control": "no-store"})


async def rooms_list(request):
    return web.json_response(
        [{"id": rid, "count": _listeners(r), "full": _listeners(r) >= MAX_ROOM,
          "kind": next(iter(r.values())).kind if r else "lan"} for rid, r in rooms.items()],
        headers={"Access-Control-Allow-Origin": "*"})


async def health(request):
    c = _counts()
    return web.Response(text=f"mc3 relay ok — {c['players']} players in {len(rooms)} rooms\n")


def make_app():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/lan", lan)
    app.router.add_get("/roam", roam)
    app.router.add_get("/players", players)
    app.router.add_get("/rooms", rooms_list)
    app.router.add_get("/dev/cheats", dev_cheats)
    social.install(app)
    social.lan_listeners = lambda: sum(_listeners(r) for r in rooms.values())
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--origins", default="", help="comma-separated allowed Origins (prod); empty = any")
    a = ap.parse_args()
    if a.origins:
        ALLOWED_ORIGINS.update(o.strip() for o in a.origins.split(",") if o.strip())
    print(f"mc3 relay on ws://{a.host}:{a.port}/lan?room=<id>  (and /roam, /players, /rooms)")
    web.run_app(make_app(), host=a.host, port=a.port, print=None)

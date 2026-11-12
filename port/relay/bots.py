"""bots.py -- test players for the MC3 web port's free-roam.

Each bot is an ordinary client of the relay: it joins a room and sends the same 'GHST'
position frames a player's page sends (web/index.html, mc3ghost), about 15 times a
second, while driving real streets near the San Diego spawn point. So one person can check
that "other players" show up -- through the real relay, the real page, the game's minimap
and the cars the engine puts in the world for them -- without a second player.

    python bots.py [--n 3] [--room mc3] [--relay ws://127.0.0.1:8090]

Stops when the file bots.off appears beside this script (tools_bots.sh stop), or on Ctrl+C.
Bots join send-only (listen=0): the relay forwards nothing to them and they take no place in
the room, so --n 200 is a stress test of the relay and of the players' pages, not of the bots.

Frame (little-endian, 55 bytes): 'GHST', u8 1, u32 id, f32 x, f32 y, f32 z, f32 heading,
10 bytes of name, 2 of country code, 10 of crew name, f32 velocity x, f32 velocity z. heading: the page turns it into the forward row of a car matrix
(cos, sin), and that row points out of the BACK of a car in this game, so a bot sends the
direction opposite to its travel.
"""
import argparse, asyncio, json, math, os, pathlib, random, struct, time
import aiohttp

OFF = pathlib.Path(__file__).with_name("bots.off")
# Whether bots.off has appeared, looked at once a second by one task: each bot looking itself,
# twice a frame, was ~6,000 file checks a second on the Windows drive at 200 bots (slow from
# WSL), which stalled them all to 0.7 frames a second (2026-11-11).
stopping = False

async def watch_off():
    global stopping
    while not stopping:
        stopping = OFF.exists()
        await asyncio.sleep(1.0)
SPAWN = (399.3, 0.2, -31.1)                      # Arcade > Cruise, San Diego (measured 2026-11-10)
NAMES = ["BotRico", "BotAngel", "BotVince", "BotOscar", "BotBishop", "BotLeo", "BotSavo"]

FLAGS = ["US", "JM", "JP", "MX", "GB", "BR", "DE"]
CREWS = ["DUB Crew", "DUB Crew", "Luxury", "", "Unbeatable", "", "Luxury"]

# Streets near the spawn, recorded 2026-11-11 from the game's own traffic cars driving their road
# network (each car's rails point, +0xC8; simplified to its corners). x, z in world units; the
# road surface there is at y = 0. A bot drives one to its end and back.
ROUTES = [
    [(381.3, 257.1), (396.3, 257.0), (401.0, 255.5), (408.6, 249.1), (411.9, 242.5), (412.3, 49.4),
     (410.7, 37.3), (407.5, 26.5), (402.6, 15.3), (236.0, -341.8)],
    [(290.2, -1.5), (388.2, -47.2), (392.7, -48.2), (750.3, -48.0)],
    [(358.8, 104.3), (290.7, 104.3), (285.4, 102.9), (282.2, 99.4), (279.2, 75.0), (273.9, 57.6),
     (254.7, 15.7), (227.1, -53.3), (134.6, -250.8)],
]
ROAD_Y = 0.0
# All over the city (tools_city_routes.py, from the game's HUD map; --near to keep every bot
# on the three streets above). Loaded in main().
CITY = []

def route_at(route, s):
    """Point and travel direction at distance s along route driven there and back."""
    seg = [math.dist(route[i], route[i + 1]) for i in range(len(route) - 1)]
    total = sum(seg)
    s %= 2 * total
    back = s > total
    if back:
        s = 2 * total - s
    for i, L in enumerate(seg):
        if s <= L or i == len(seg) - 1:
            (x0, z0), (x1, z1) = route[i], route[i + 1]
            f = min(1.0, s / L) if L else 0.0
            dx, dz = (x1 - x0) / (L or 1), (z1 - z0) / (L or 1)
            if back:
                dx, dz = -dx, -dz
            return x0 + (x1 - x0) * f, z0 + (z1 - z0) * f, dx, dz
        s -= L

def frame(bot_id, x, y, z, heading, name, cc="", crew="", vx=0.0, vz=0.0, car=""):
    # ..., 10 bytes of name, 2 of country (ISO 3166), 10 of crew name, velocity x z (units/s),
    # 16 of car (the game's internal name, vp_jetta_03: the page draws a real car of it)
    return struct.pack("<4sBIffff10s2s10sff16s", b"GHST", 1, bot_id, x, y, z, heading,
                       name.encode()[:10], cc.encode()[:2], crew.encode()[:10], vx, vz, car.encode()[:16])

# 'GREC' car records (paint, parts, plate) the bots send every 5 s, from bot_records.json: their real
# cars are built from them (the page's sendRecord); bot k sends record k % count
try:
    _recs = json.load(open(pathlib.Path(__file__).with_name("bot_records.json")))
    RECORDS = [bytes.fromhex(v) for k, v in sorted(_recs.items()) if not k.startswith("_")]
except Exception:
    RECORDS = []

def record_frame(bot_id, rec):
    return b"GREC" + struct.pack("<I", bot_id) + rec[:223].ljust(223, b"\0")

STILL = 0                                      # --still N: the first N bots stand still (tests)
PARK = None                                    # --park X,Z: where they stand (else their route's start)
SWAP = 0.0                                     # --swap SECS: the bots change car (Jetta <-> Eclipse) every SECS,
                                               # like a player who went to the garage (2026-11-12, owner: invisible after)
SWAP_CARS = [("vp_jetta_03", "jetta"), ("vp_eclipse_04", "eclipse")]
CARS = ["vp_jetta_03", "vp_golfr32_04", "vp_eclipse_04", "vp_lancer_04", "vp_350z_04", "vp_srt4_04"]   # --cars a,b,...

async def bot(session, relay, room, k):
    name = NAMES[k] if k < len(NAMES) else f"Bot{k:03d}"
    bot_id = 0xB0700000 + k
    # each on one of the streets, at its own speed (14-30 units/s, a city speed for any k),
    # starting part of the way along so many bots spread out
    # the first three keep to the streets by the spawn (someone to see straight away); the
    # rest are spread over the whole city
    if CITY and k >= len(ROUTES):
        route = CITY[(k - len(ROUTES)) % len(CITY)]
        s = random.Random(k).uniform(0, 4000)    # its own place and direction along it
    else:
        route = ROUTES[k % len(ROUTES)]
        s = 60.0 * k + 37.0 * (k // len(ROUTES))
    speed = 0 if k < STILL else 14 + (k * 7) % 17  # world units per second
    while not stopping:
        try:
            async with session.ws_connect(f"{relay}/lan?room={room}&name={name}&listen=0", heartbeat=20) as ws:
                print(f"{name}: in room {room}", flush=True)
                last = time.monotonic(); rec_at = 0.0
                while not stopping and not ws.closed:
                    swap_i = (int(time.monotonic() // SWAP) + k) % 2 if SWAP else -1
                    if RECORDS and time.monotonic() - rec_at > 5.0:
                        rec_at = time.monotonic()
                        rec_n = getattr(bot, 'jitter', 0) and int(time.monotonic() // 5)
                        rec = RECORDS[(k + (rec_n or 0)) % len(RECORDS)]
                        if swap_i >= 0 and SWAP_CARS[swap_i][1] in _recs:   # the record of the car it drives now
                            rec = bytes.fromhex(_recs[SWAP_CARS[swap_i][1]])
                        await ws.send_bytes(record_frame(bot_id, rec))
                    now = time.monotonic(); dt = now - last; last = now
                    s += speed * dt
                    x, z, vx, vz = route_at(route, s + (0.5 if speed == 0 else 0))   # parked: a direction to face
                    if speed == 0 and PARK:                    # side by side, 7 units apart, facing +x
                        x, z, vx, vz = PARK[0] + 7.0 * k, PARK[1], 1.0, 0.0
                    await ws.send_bytes(frame(bot_id, x, ROAD_Y, z, math.atan2(-vz, -vx), name,
                                              FLAGS[k % len(FLAGS)], CREWS[k % len(CREWS)],
                                              vx * speed, vz * speed, SWAP_CARS[swap_i][0] if swap_i >= 0 else (CARS[k % len(CARS)] if CARS else "")))
                    await asyncio.sleep(0.066)
        except Exception as e:                                         # relay restarting, room full, ...
            print(f"{name}: {e!r}; retrying", flush=True)
        await asyncio.sleep(3)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--room", default="mc3")
    ap.add_argument("--relay", default="ws://127.0.0.1:8090")
    ap.add_argument("--near", action="store_true", help="every bot on the streets by the spawn")
    ap.add_argument("--still", type=int, default=0, help="the first N bots stand still (wheels, tag tests)")
    ap.add_argument("--park", default="", help="X,Z where the still bots stand (side by side)")
    ap.add_argument("--jitter", action="store_true", help="each send of the car record alternates between records (tests a changing record)")
    ap.add_argument("--swap", type=float, default=0.0, help="change car (Jetta <-> Eclipse) every SECS")
    ap.add_argument("--cars", default=None, help="comma-separated car names the bots drive ('' = none sent)")
    a = ap.parse_args()
    global STILL, PARK, CARS, SWAP
    STILL = max(0, a.still)
    SWAP = max(0.0, a.swap)
    if a.park: PARK = tuple(float(v) for v in a.park.split(","))
    if a.cars is not None: CARS = [c for c in a.cars.split(",") if c]
    bot.jitter = 1 if a.jitter else 0
    cf = pathlib.Path(__file__).with_name("city_routes.json")
    if not a.near and cf.exists():
        CITY.extend([tuple(p) for p in r] for r in json.loads(cf.read_text())["routes"])
        print(f"{len(CITY)} city routes", flush=True)
    if OFF.exists():
        OFF.unlink()
    # no connection cap: aiohttp's default (100) stopped a 200-bot run halfway
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        await asyncio.gather(watch_off(), *(bot(session, a.relay, a.room, k) for k in range(max(1, min(a.n, 500)))))
    print("bots stopped", flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

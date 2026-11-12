"""latejoin.py -- one test player that joins the room AFTER someone is already in it.

Reproduces "players already in free-roam don't see a player who joins later": run it while
a page is in San Diego free-roam and check the page's mc3ghost.others / engine.cars.
    python latejoin.py [--room mc3] [--relay ws://127.0.0.1:8090] [--secs 90] [--name LateJoin]
Drives the first bot street (bots.ROUTES[0]) there and back at 20 units/s.
"""
import argparse, asyncio, math, time, aiohttp
from bots import ROUTES, ROAD_Y, route_at, frame

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="mc3"); ap.add_argument("--relay", default="ws://127.0.0.1:8090")
    ap.add_argument("--secs", type=float, default=90); ap.add_argument("--name", default="LateJoin")
    a = ap.parse_args()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(f"{a.relay}/lan?room={a.room}&name={a.name}") as ws:
            print("joined", flush=True)
            t0 = last = time.monotonic(); dist = 30.0; got = 0
            while time.monotonic() - t0 < a.secs:
                now = time.monotonic(); dist += 20 * (now - last); last = now
                x, z, dx, dz = route_at(ROUTES[0], dist)
                await ws.send_bytes(frame(0xB07F0001, x, ROAD_Y, z, math.atan2(-dz, -dx), a.name, "GB", "Test"))
                try:
                    while True:
                        m = await ws.receive(timeout=0.001)
                        if m.type == aiohttp.WSMsgType.BINARY: got += 1
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.066)
            print("done; frames received from others:", got, flush=True)

asyncio.run(main())

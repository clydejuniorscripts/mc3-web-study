"""vis_test.py -- do two players who join at different times see each other? (relay test)

Player A joins and sends position frames ('GHST', 15 a second, like the page); player B joins
--gap seconds later and does the same; then for --secs each counts the frames it received from
the other. Both should get ~15/s. Joins exactly as the page does (/lan?room=..&batch=1) and
splits 'GBAT' batches.
    python vis_test.py [--relay ws://127.0.0.1:8090] [--room vistest] [--gap 3] [--secs 6]
"""
import argparse, asyncio, struct, time, aiohttp
from bots import frame

async def player(session, url, pid, name, other, t_end, got, start_delay):
    await asyncio.sleep(start_delay)
    async with session.ws_connect(url, heartbeat=20) as ws:
        async def send():
            while time.monotonic() < t_end:
                await ws.send_bytes(frame(pid, 400.0, 0.0, -30.0, 0.0, name, "US", "", 0.0, 0.0))
                await asyncio.sleep(1 / 15)
        async def recv():
            while time.monotonic() < t_end:
                try: m = await asyncio.wait_for(ws.receive(), 0.5)
                except asyncio.TimeoutError: continue
                if m.type != aiohttp.WSMsgType.BINARY: continue
                b = m.data; parts = []
                if b[:4] == b"GBAT":
                    o = 4
                    while o + 2 <= len(b):
                        n = int.from_bytes(b[o:o + 2], "little"); parts.append(b[o + 2:o + 2 + n]); o += 2 + n
                else: parts = [b]
                for p in parts:
                    if p[:4] == b"GHST" and len(p) >= 9:
                        sid = struct.unpack_from("<I", p, 5)[0]
                        got.setdefault(sid, 0); got[sid] += 1
        await asyncio.gather(send(), recv())

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", default="ws://127.0.0.1:8090"); ap.add_argument("--room", default="vistest")
    ap.add_argument("--gap", type=float, default=3); ap.add_argument("--secs", type=float, default=6)
    a = ap.parse_args()
    url = f"{a.relay}/lan?room={a.room}&batch=1"
    A, B = 0xA1A10001, 0xB2B20002
    gotA, gotB = {}, {}
    t_end = time.monotonic() + a.gap + a.secs
    async with aiohttp.ClientSession() as s:
        await asyncio.gather(player(s, url, A, "TestFirst", B, t_end, gotA, 0),
                             player(s, url, B, "TestLast", A, t_end, gotB, a.gap))
    print(f"first-joiner saw the late joiner: {gotA.get(B, 0)} frames ({gotA.get(B, 0)/a.secs:.1f}/s)")
    print(f"late joiner saw the first-joiner: {gotB.get(A, 0)} frames ({gotB.get(A, 0)/a.secs:.1f}/s)")
    print("ids A saw:", [hex(k) for k in gotA], " ids B saw:", [hex(k) for k in gotB])

asyncio.run(main())

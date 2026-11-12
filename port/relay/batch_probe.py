"""batch_probe.py -- join a room with batch=1 and count messages and frames a second (relay test).
    python batch_probe.py [--secs 10] [--relay ws://127.0.0.1:8090] [--room mc3]"""
import argparse, asyncio, time, aiohttp
async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--secs", type=float, default=10)
    ap.add_argument("--relay", default="ws://127.0.0.1:8090"); ap.add_argument("--room", default="mc3")
    a = ap.parse_args(); msgs = frames = 0; ids = set(); t0 = time.monotonic()
    async with aiohttp.ClientSession() as s, s.ws_connect(f"{a.relay}/lan?room={a.room}&name=probe&batch=1") as ws:
        while time.monotonic() - t0 < a.secs:
            try: m = await asyncio.wait_for(ws.receive(), 1)
            except asyncio.TimeoutError: continue
            if m.type != aiohttp.WSMsgType.BINARY: continue
            b = m.data; msgs += 1; parts = []
            if b[:4] == b"GBAT":
                o = 4
                while o + 2 <= len(b): n = int.from_bytes(b[o:o+2], "little"); parts.append(b[o+2:o+2+n]); o += 2 + n
            else: parts = [b]
            for p in parts:
                frames += 1
                if p[:4] == b"GHST": ids.add(int.from_bytes(p[5:9], "little"))
    d = time.monotonic() - t0
    print(f"{msgs/d:.0f} messages/s, {frames/d:.0f} frames/s, {frames/max(1,msgs):.0f} frames per message, {len(ids)} senders")
asyncio.run(main())

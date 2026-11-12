"""listen.py -- join a room without sending and count each player's position frames (diagnosis).
    python listen.py [--room mc3] [--relay ws://127.0.0.1:8090] [--secs 10]"""
import argparse, asyncio, struct, time, aiohttp, collections
async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--room", default="mc3")
    ap.add_argument("--relay", default="ws://127.0.0.1:8090"); ap.add_argument("--secs", type=float, default=10)
    a = ap.parse_args(); n = collections.Counter(); names = {}; gaps = collections.defaultdict(float); last = {}
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(f"{a.relay}/lan?room={a.room}&name=listener") as ws:
            t0 = time.monotonic()
            while time.monotonic() - t0 < a.secs:
                try: m = await ws.receive(timeout=0.5)
                except asyncio.TimeoutError: continue
                if m.type != aiohttp.WSMsgType.BINARY or m.data[:4] != b"GHST": continue
                pid = struct.unpack_from("<I", m.data, 5)[0]; now = time.monotonic()
                n[pid] += 1; names[pid] = m.data[25:35].split(b"\0")[0].decode(errors="replace")
                if pid in last: gaps[pid] = max(gaps[pid], now - last[pid])
                last[pid] = now
    for pid, c in n.most_common():
        print(f"{pid:08x} {names[pid]:<10} {c / a.secs:5.1f}/s  longest gap {gaps[pid]*1000:5.0f} ms  len {len(m.data)}")
asyncio.run(main())

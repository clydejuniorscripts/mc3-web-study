"""hol_test.py -- a stuck player must not slow anyone else down (relay head-of-line test).
Starts nothing itself: run relay.py on --port first. Sender at 15/s, a member that never
reads, and a listener that counts what arrives."""
import argparse, asyncio, struct, time, aiohttp
async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--relay", default="ws://127.0.0.1:8091"); a = ap.parse_args()
    async with aiohttp.ClientSession() as s:
        stuck = await s.ws_connect(f"{a.relay}/lan?room=t&name=stuck")          # joins, never reads
        lis = await s.ws_connect(f"{a.relay}/lan?room=t&name=lis")
        snd = await s.ws_connect(f"{a.relay}/lan?room=t&name=snd")
        async def send():
            big = b"GHST" + b"\0" * 60000                                       # fill the stuck one's buffers fast
            for k in range(150):
                await snd.send_bytes(big); await asyncio.sleep(1 / 15)
        got = 0; t0 = time.monotonic(); task = asyncio.ensure_future(send())
        while time.monotonic() - t0 < 10.5:
            try:
                m = await lis.receive(timeout=0.5)
                if m.type == aiohttp.WSMsgType.BINARY: got += 1
            except asyncio.TimeoutError: pass
        await task
        print(f"listener got {got} of 150 frames ({got / 10:.1f}/s) with a stuck member in the room")
asyncio.run(main())

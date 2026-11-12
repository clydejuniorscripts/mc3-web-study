"""Load + latency check for relay.py. Several full rooms (8 players each) exchange
48-byte ghost frames at 20 Hz, like real free-roam. Verifies delivery rate,
relay-added latency, and throughput. Run: python load_test.py"""
import asyncio, time, struct
from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer
from relay import make_app, MAX_ROOM

HZ = 20
DUR = 3.0
FRAME = 48
ROOMS = 3


async def player(sess, wsbase, room, idx, stats):
    ws = await sess.ws_connect(f"{wsbase}/roam?room={room}&name=p{idx}")
    stats["ws"].append(ws)
    got = {"n": 0, "lat": 0.0}

    async def reader():
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                ts = struct.unpack_from("<d", msg.data, 1)[0]
                got["n"] += 1
                got["lat"] += time.perf_counter() - ts

    rt = asyncio.create_task(reader())
    end = time.perf_counter() + DUR
    sent = 0
    while time.perf_counter() < end:
        buf = bytearray(FRAME)
        buf[0] = idx
        struct.pack_into("<d", buf, 1, time.perf_counter())
        await ws.send_bytes(bytes(buf))
        sent += 1
        await asyncio.sleep(1 / HZ)
    await asyncio.sleep(0.3)   # let the last frames arrive
    rt.cancel()
    stats["sent"] += sent
    stats["recv"] += got["n"]
    stats["lat"] += got["lat"]
    stats["latn"] += got["n"]


async def main():
    server = TestServer(make_app())
    await server.start_server()
    wsbase = f"ws://{server.host}:{server.port}"
    sess = ClientSession()
    stats = {"sent": 0, "recv": 0, "lat": 0.0, "latn": 0, "ws": []}
    try:
        tasks = [player(sess, wsbase, f"room{r}", i, stats)
                 for r in range(ROOMS) for i in range(MAX_ROOM)]
        t0 = time.perf_counter()
        await asyncio.gather(*tasks)
        dt = time.perf_counter() - t0

        exp = stats["sent"] * (MAX_ROOM - 1)          # each frame -> peers in room
        pct = 100 * stats["recv"] / exp if exp else 0
        lat = (stats["lat"] / stats["latn"] * 1000) if stats["latn"] else 0
        print(f"rooms={ROOMS}  players/room={MAX_ROOM}  dur={DUR}s  frame={FRAME}B @ {HZ}Hz")
        print(f"sent={stats['sent']}  recv={stats['recv']}  expected~{exp}  ({pct:.1f}% delivered)")
        print(f"relay-added latency: avg {lat:.2f} ms")
        print(f"throughput: {stats['recv'] / dt:.0f} frames/s forwarded "
              f"(~{stats['recv'] * FRAME / dt / 1024:.0f} KB/s)")
        assert pct >= 95.0, f"too many dropped ({pct:.1f}%)"
        assert lat < 50.0, f"latency too high ({lat:.1f} ms)"
        print("\nLOAD TEST PASSED")
    finally:
        for ws in stats["ws"]:
            try: await ws.close()
            except Exception: pass
        await sess.close()
        await server.close()


asyncio.run(main())

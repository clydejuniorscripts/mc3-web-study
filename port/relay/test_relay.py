"""Self-contained test for relay.py. Starts the app on an ephemeral port and
exercises forwarding, /players, the room cap and the frame-size limit."""
import asyncio
from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestServer
from relay import make_app, MAX_FRAME, MAX_ROOM


async def recv_bin(ws, timeout=2.0):
    msg = await asyncio.wait_for(ws.receive(), timeout)
    assert msg.type == WSMsgType.BINARY, msg
    return msg.data


async def main():
    server = TestServer(make_app())
    await server.start_server()
    http = f"http://{server.host}:{server.port}"
    wsb = f"ws://{server.host}:{server.port}"
    sess = ClientSession()
    try:
        a = await sess.ws_connect(f"{wsb}/lan?room=r1&name=A")
        b = await sess.ws_connect(f"{wsb}/lan?room=r1&name=B")
        await asyncio.sleep(0.05)

        # /players counts both
        pj = await (await sess.get(f"{http}/players")).json()
        assert pj["players"] == 2 and pj["rooms"][0]["count"] == 2, pj
        print("ok  /players =", pj["players"])

        # forward A -> B and B -> A
        await a.send_bytes(b"\x01\x02hello")
        assert await recv_bin(b) == b"\x01\x02hello"
        await b.send_bytes(b"world\xff")
        assert await recv_bin(a) == b"world\xff"
        print("ok  binary forward both directions")

        # sender does not get its own frame back
        await a.send_bytes(b"solo")
        assert await recv_bin(b) == b"solo"
        try:
            await asyncio.wait_for(a.receive(), 0.3)
            raise AssertionError("A received its own frame")
        except asyncio.TimeoutError:
            pass
        print("ok  no self-echo")

        # room cap: fill a room to 8, the 9th is refused (409 -> handshake error)
        full = [await sess.ws_connect(f"{wsb}/lan?room=cap&name=p{i}") for i in range(MAX_ROOM)]
        try:
            await sess.ws_connect(f"{wsb}/lan?room=cap&name=p9")
            raise AssertionError("9th client was allowed")
        except WSServerHandshakeError as e:
            assert e.status == 409, e
        print(f"ok  room cap at {MAX_ROOM} (9th refused 409)")

        # oversized frame is dropped; the socket stays alive
        await a.send_bytes(b"x" * (MAX_FRAME + 10))
        try:
            await asyncio.wait_for(b.receive(), 0.3)
            raise AssertionError("oversized frame was forwarded")
        except asyncio.TimeoutError:
            pass
        await a.send_bytes(b"after-big")
        assert await recv_bin(b) == b"after-big"
        print("ok  oversized frame dropped, socket survives")

        # closing empties the room
        for ws in [a, b, *full]:
            await ws.close()
        await asyncio.sleep(1.2)   # let sockets close AND the 1 s /players cache expire
        pj = await (await sess.get(f"{http}/players")).json()
        assert pj["players"] == 0 and pj["rooms"] == [], pj
        print("ok  rooms empty after disconnect")
        print("\nALL RELAY TESTS PASSED")
    finally:
        await sess.close()
        await server.close()


asyncio.run(main())

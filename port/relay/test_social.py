"""Checks for social.py + the bigger rooms in relay.py, on a private relay (in-memory DB).
Run:  python test_social.py      (prints PASS/FAIL lines and a summary)"""
import asyncio, json, os, struct, sys, time, secrets
os.environ["MC3_SOCIAL_DB"] = ":memory:"
from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer
from relay import make_app, MAX_ROOM

fails = 0
def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what); fails += 0 if ok else 1


def ghst(gid, x, z, crew=b"FAKE"):
    b = bytearray(71); b[0:4] = b"GHST"; b[4] = 1
    struct.pack_into("<Iffff", b, 5, gid, x, 0.0, z, 0.0)
    b[25:30] = b"Bob\0\0"; b[35:37] = b"US"; b[37:37 + len(crew)] = crew
    return bytes(b)


class P:
    """one player: a /lan socket (positions) and a /social socket (everything else)"""
    def __init__(self, name):
        self.name = name; self.pid = secrets.token_hex(16); self.key = secrets.token_hex(16)
        self.gid = int(self.pid[:8], 16); self.msgs = []; self.frames = []
    async def open(self, sess, base, room="mc3", lan=True):
        if lan:
            self.lan = await sess.ws_connect(f"{base}/lan?room={room}&batch=1")
            asyncio.ensure_future(self._rd(self.lan, self.frames))
        self.soc = await sess.ws_connect(f"{base}/social?room={room}")
        asyncio.ensure_future(self._rd(self.soc, self.msgs))
        await self.say(t="hi", pid=self.pid, key=self.key, gid=self.gid, name=self.name, cc="JM")
    async def _rd(self, ws, out):
        async for m in ws:
            if m.type == WSMsgType.TEXT and m.data != "pong": out.append(json.loads(m.data))
            elif m.type == WSMsgType.BINARY: out.append(m.data)
    async def say(self, **m): await self.soc.send_str(json.dumps(m))
    def got(self, **want):
        return [m for m in self.msgs if isinstance(m, dict) and all(m.get(k) == v for k, v in want.items())]
    def last_me(self):
        ms = self.got(t="me"); return ms[-1] if ms else None


async def main():
    srv = TestServer(make_app()); await srv.start_server()
    base = f"ws://{srv.host}:{srv.port}"
    async with ClientSession() as sess:
        # 1. a room bigger than 8: 40 players all hear each other
        check(MAX_ROOM >= 40, f"MAX_ROOM is {MAX_ROOM}")
        socks = []
        for i in range(40):
            socks.append(await sess.ws_connect(f"{base}/lan?room=big&batch=1"))
        got = [0] * 40
        async def rd(i):
            async for m in socks[i]:
                if m.type == WSMsgType.BINARY:
                    d = m.data
                    if d[:4] == b"GBAT":
                        o = 4
                        while o + 2 <= len(d):
                            n = d[o] | d[o + 1] << 8; o += 2 + n; got[i] += 1
                    else: got[i] += 1
        tasks = [asyncio.ensure_future(rd(i)) for i in range(40)]
        for rep in range(20):                                   # 1 s at 20 Hz
            for i, s in enumerate(socks): await s.send_bytes(ghst(1000 + i, i * 10.0, 0.0))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.4)
        exp = 20 * 39
        check(min(got) >= exp * 0.97, f"40 in one room: each got {min(got)}..{max(got)} of {exp} frames")
        r = await sess.get(f"http://{srv.host}:{srv.port}/players?rooms=big"); body = await r.json()
        check(body["rooms"][0]["count"] == 40 and not body["rooms"][0]["full"], f"/players: {body['rooms']}")
        for s in socks: await s.close()
        for t in tasks: t.cancel()

        # 2. identity
        a, b, c = P("Alice"), P("Bob"), P("Cara")
        for p in (a, b, c): await p.open(sess, base)
        await asyncio.sleep(0.2)
        check(a.last_me() and a.last_me()["pid"] == a.pid, "hello registers the player id")
        evil = P("Evil"); evil.pid = a.pid
        await evil.open(sess, base, lan=False); await asyncio.sleep(0.1)
        check(bool(evil.got(t="err")), "someone else's player id with the wrong key is refused")
        ros = c.got(t="roster")
        check(ros and {x["pid"] for x in ros[-1]["players"]} >= {a.pid, b.pid, c.pid}, "roster lists the room")

        # 3. crews
        await a.say(t="crew", op="create", tag="DUBS", open=False); await asyncio.sleep(0.1)
        check(a.last_me()["crew"] and a.last_me()["crew"]["tag"] == "DUBS" and a.last_me()["role"] == "leader", "create crew -> leader")
        await b.say(t="crew", op="create", tag="dubs"); await asyncio.sleep(0.1)
        check(bool(b.got(t="err")), "tags are unique ignoring case")
        await b.say(t="crew", op="join", tag="DUBS"); await asyncio.sleep(0.1)
        check(not b.last_me()["crew"], "invite-only crew refuses an uninvited join")
        await a.say(t="crew", op="invite", pid=b.pid); await asyncio.sleep(0.1)
        check(b.last_me()["invites"] and b.last_me()["invites"][0]["tag"] == "DUBS", "invite reaches the player")
        await b.say(t="crew", op="join", tag="DUBS"); await asyncio.sleep(0.1)
        check(b.last_me()["crew"] and len(b.last_me()["crew"]["members"]) == 2, "invited player joins")
        check(any(m.get("p", {}).get("pid") == b.pid and m["p"]["crew"] == "DUBS" for m in c.got(t="upd")), "the room sees B's new crew tag")
        r = await sess.get(f"http://{srv.host}:{srv.port}/crews"); lst = await r.json()
        check(lst and lst[0]["tag"] == "DUBS" and lst[0]["members"] == 2 and lst[0]["online"] == 2, f"GET /crews {lst}")

        # crew tag on the position frames is the real one
        c.frames.clear()
        await a.lan.send_bytes(ghst(a.gid, 0.0, 0.0, b"LIES")); await asyncio.sleep(0.15)
        def frames_of(p):
            out = []
            for d in p.frames:
                if d[:4] == b"GBAT":
                    o = 4
                    while o + 2 <= len(d):
                        n = d[o] | d[o + 1] << 8; out.append(d[o + 2:o + 2 + n]); o += 2 + n
                else: out.append(d)
            return out
        fr = [f for f in frames_of(c) if struct.unpack_from("<I", f, 5)[0] == a.gid]
        check(fr and fr[-1][37:47].rstrip(b"\0") == b"DUBS", f"relay rewrites the crew in A's frame: {fr[-1][37:47] if fr else None}")
        await c.lan.send_bytes(ghst(c.gid, 100.0, 0.0, b"DUBS")); await asyncio.sleep(0.15)
        fr = [f for f in frames_of(a) if struct.unpack_from("<I", f, 5)[0] == c.gid]
        check(fr and fr[-1][37:47].rstrip(b"\0") == b"", "a player not in DUBS can't wear its tag")

        # 4. chat
        for p in (a, b, c): p.msgs.clear()
        await a.say(t="chat", ch="room", text="hello\x07 everyone"); await asyncio.sleep(0.1)
        check(all(p.got(t="chat", ch="room") and p.got(t="chat")[0]["text"] == "hello everyone" for p in (a, b, c)), "room chat reaches all (control chars stripped)")
        await a.say(t="chat", ch="crew", text="crew only"); await asyncio.sleep(0.1)
        check(b.got(t="chat", ch="crew") and not c.got(t="chat", ch="crew"), "crew chat: crew yes, others no")
        # positions: A at 0,0 ; B at 1000,0 ; C at 100,0 (sent above)
        await b.lan.send_bytes(ghst(b.gid, 1000.0, 0.0)); await a.lan.send_bytes(ghst(a.gid, 0.0, 0.0)); await asyncio.sleep(0.1)
        await a.say(t="chat", ch="near", text="anyone close"); await asyncio.sleep(0.1)
        check(c.got(t="chat", ch="near") and not b.got(t="chat", ch="near") and a.got(t="chat", ch="near"), "nearby chat: 100 m yes, 1000 m no")
        await a.say(t="chat", ch="room", text="x" * 500); await asyncio.sleep(0.1)
        check(len(c.got(t="chat")[-1]["text"]) == 160, "length cap 160")
        for i in range(8): await c.say(t="chat", ch="room", text=f"spam {i}")
        await asyncio.sleep(0.15)
        check(len([m for m in a.got(t="chat") if m["text"].startswith("spam")]) == 5 and c.got(t="sys"), "rate limit: 5 per 8 s")

        # 5. voice signalling
        a.msgs.clear(); b.msgs.clear(); c.msgs.clear()
        await a.say(t="voice", on=True); await a.say(t="rtc", to=b.pid, d={"sdp": "x"}); await a.say(t="talk", ch="crew", on=True)
        await asyncio.sleep(0.1)
        check(b.got(t="rtc", **{"from": a.pid}) and not c.got(t="rtc"), "rtc goes to the one player")
        check(b.got(t="talk", ch="crew") and c.got(t="talk"), "talk state reaches the room")
        check(any(m.get("p", {}).get("v") for m in c.got(t="upd")), "voice on shows in the roster")

        # crew mates in another room still get crew chat and rtc
        d = P("Dan"); await d.open(sess, base, room="other", lan=False); await asyncio.sleep(0.1)
        await a.say(t="crew", op="invite", pid=d.pid); await asyncio.sleep(0.1)
        await d.say(t="crew", op="join", tag="dubs"); await asyncio.sleep(0.1)
        await a.say(t="chat", ch="crew", text="across rooms"); await a.say(t="rtc", to=d.pid, d={"x": 1}); await asyncio.sleep(0.1)
        check(d.got(t="chat", ch="crew") and d.got(t="rtc"), "crew chat and voice reach a crew mate in another room")

        # leader leaves -> next member leads; last one out deletes the crew
        await a.say(t="crew", op="leave"); await asyncio.sleep(0.1)
        check(b.last_me()["role"] == "leader", "leader leaves: the longest-standing member leads")
        await b.say(t="crew", op="leave"); await d.say(t="crew", op="leave"); await asyncio.sleep(0.1)
        r = await sess.get(f"http://{srv.host}:{srv.port}/crews"); lst = await r.json()
        check(lst == [], "empty crew is removed")
        # HTTP crew API
        r = await sess.post(f"http://{srv.host}:{srv.port}/crew", json={"pid": c.pid, "key": c.key, "op": "create", "tag": "Web Crew"})
        j = await r.json(); check(j["ok"] and j["me"]["crew"]["tag"] == "Web Crew", "POST /crew create")
        r = await sess.post(f"http://{srv.host}:{srv.port}/crew", json={"pid": c.pid, "key": "wrongwrongwrong1", "op": "leave"})
        check(r.status == 403, "POST /crew with the wrong key is refused")

        # 6. claimed names, bans, mutes
        H = f"http://{srv.host}:{srv.port}"
        e, f = P("Eddie"), P("Eddie")
        await e.open(sess, base); await asyncio.sleep(0.1)
        await e.say(t="claim"); await asyncio.sleep(0.1)
        check(e.last_me()["claimed"] == "Eddie", "claim a name")
        await f.open(sess, base); await asyncio.sleep(0.15)
        nm = f.got(t="name")
        check(nm and nm[0]["name"].startswith("P-"), f"someone else asking for a claimed name gets a stand-in: {nm[0]['name'] if nm else None}")
        a.frames.clear()
        await f.lan.send_bytes(ghst(f.gid, 0.0, 0.0)); await asyncio.sleep(0.15)
        fr = [x for x in frames_of(a) if struct.unpack_from("<I", x, 5)[0] == f.gid]
        check(fr and fr[-1][25:35].rstrip(bytes(1)).startswith(b"P-"), "the impostor's frames carry the stand-in name")
        await f.say(t="claim"); await asyncio.sleep(0.1)
        check(not f.last_me()["claimed"], "a stand-in name can't be claimed")
        # admin: local only
        r = await sess.get(f"{H}/admin/find?q=eddie", headers={"Cf-Connecting-Ip": "1.2.3.4"})
        check(r.status == 403, "admin refused through the tunnel")
        rows = await (await sess.get(f"{H}/admin/find?q=eddie")).json()
        check(any(x["claimed"] == "Eddie" for x in rows), "admin find by claimed name")
        # mute
        await sess.post(f"{H}/admin/mute", json={"pid": e.pid, "minutes": 5, "reason": "spam"}); await asyncio.sleep(0.1)
        a.msgs.clear(); await e.say(t="chat", ch="room", text="can you hear me"); await asyncio.sleep(0.1)
        check(not a.got(t="chat") and any("muted" in (m.get("text") or "") for m in e.got(t="sys")), "a muted player's chat goes nowhere")
        await sess.post(f"{H}/admin/unmute", json={"pid": e.pid}); await e.say(t="chat", ch="room", text="back"); await asyncio.sleep(0.1)
        check(a.got(t="chat"), "unmute")
        # ban: kicked at once, frames dropped, told the number and reason, refused on return
        await e.lan.send_bytes(ghst(e.gid, 0.0, 0.0)); await asyncio.sleep(0.05)
        r = await (await sess.post(f"{H}/admin/ban", json={"pid": e.pid, "reason": "cheating", "days": 1})).json()
        await asyncio.sleep(0.5)
        bm = e.got(t="banned")
        check(r["ok"] and bm and bm[0]["n"] == r["n"] and bm[0]["reason"] == "cheating" and bm[0]["until"], f"ban reaches the player: {bm}")
        check(e.soc.closed, "banned player's chat socket closed")
        await e.lan.send_bytes(ghst(e.gid, 0.0, 0.0)); await asyncio.sleep(0.3)
        check(e.lan.closed, "banned player's position socket closed on its next frame")
        e2 = P("Eddie"); e2.pid, e2.key = e.pid, e.key
        await e2.open(sess, base, lan=False); await asyncio.sleep(0.15)
        check(e2.got(t="banned"), "banned player refused when coming back")
        await sess.post(f"{H}/admin/unban", json={"pid": e.pid})
        e3 = P("Eddie"); e3.pid, e3.key = e.pid, e.key
        await e3.open(sess, base, lan=False); await asyncio.sleep(0.15)
        check(e3.last_me() and not e3.got(t="banned"), "unban")

        # 7. cloud saves (the page encrypts; the host stores blobs per locker)
        L = "ab" * 32; blob = b"MC3C" + b"x" * 100
        r = await sess.get(f"{H}/cloud/{L}"); check(r.status == 404, "no locker yet")
        r = await sess.put(f"{H}/cloud/{L}", data=blob, headers={"X-Cloud-Write": "t" * 40}); check(r.status == 200, "first upload makes the locker")
        r = await sess.put(f"{H}/cloud/{L}", data=b"MC3C" + b"y" * 50, headers={"X-Cloud-Write": "u" * 40}); check(r.status == 403, "wrong write token refused")
        r = await sess.put(f"{H}/cloud/{L}", data=b"nope" * 10, headers={"X-Cloud-Write": "t" * 40}); check(r.status == 400, "not a cloud save refused")
        for k in range(7):
            await sess.put(f"{H}/cloud/{L}", data=b"MC3C" + bytes([k]) * 64, headers={"X-Cloud-Write": "t" * 40}); await asyncio.sleep(0.002)
        r = await sess.get(f"{H}/cloud/{L}"); b = await r.read()
        info = await (await sess.get(f"{H}/cloud/{L}/info")).json()
        check(b == b"MC3C" + bytes([6]) * 64 and info["versions"] == 5, f"newest blob back, 5 versions kept: {info}")

        # 8. friends
        g, h = P("Gina"), P("Hank")
        await g.open(sess, base); await h.open(sess, base, room="other", lan=False); await asyncio.sleep(0.15)
        await g.say(t="claim"); await asyncio.sleep(0.05)
        await h.say(t="friend", op="add", name="gina"); await asyncio.sleep(0.15)
        fl = g.got(t="friends")[-1]
        check(fl["in"] and fl["in"][0]["pid"] == h.pid, "request by (claimed) name reaches across rooms")
        await h.say(t="pm", to=g.pid, text="hi gina"); await asyncio.sleep(0.1)
        check(not g.got(t="pm"), "no private messages before accepting")
        await g.say(t="friend", op="accept", pid=h.pid); await asyncio.sleep(0.15)
        check(g.got(t="friends")[-1]["list"] and h.got(t="friends")[-1]["list"][0]["pid"] == g.pid, "accept: both lists")
        hf = h.got(t="friends")[-1]["list"][0]
        check(hf["online"] and hf["room"] == "mc3" and hf["gid"] == g.gid, f"friend shows online, room and ghost id: {hf}")
        await h.say(t="pm", to=g.pid, text="hi gina"); await asyncio.sleep(0.1)
        check(g.got(t="pm") and g.got(t="pm")[-1]["text"] == "hi gina" and h.got(t="pm"), "private message to a friend (and an echo)")
        await g.lan.send_bytes(ghst(g.gid, 321.0, -55.0)); await asyncio.sleep(0.1)
        await h.say(t="where", pid=g.pid); await asyncio.sleep(0.1)
        w = h.got(t="where")[-1]
        check(w["room"] == "mc3" and abs(w["x"] - 321) < 0.01 and w["roam"], f"where is my friend: {w}")
        await g.soc.close(); await asyncio.sleep(0.2)
        check(not h.got(t="friends")[-1]["list"][0]["online"], "friend going offline is seen")
        await h.say(t="pm", to=g.pid, text="while you were out"); await asyncio.sleep(0.1)
        g2 = P("Gina"); g2.pid, g2.key = g.pid, g.key
        await g2.open(sess, base, lan=False); await asyncio.sleep(0.15)
        check(any(m.get("old") and m["text"] == "while you were out" for m in g2.got(t="pm")), "offline message delivered on return")
        await h.say(t="friend", op="remove", pid=g.pid); await asyncio.sleep(0.1)
        check(not g2.got(t="friends")[-1]["list"], "remove")

        # 9. playing now + race lobbies + results
        on = await (await sess.get(f"{H}/online")).json()
        check(on["online"] >= 3 and "lobbies" in on, f"GET /online {on}")
        r1, r2, r3 = P("Ray"), P("Rita"), P("Rob")
        for q in (r1, r2, r3): await q.open(sess, base, lan=False)
        await asyncio.sleep(0.1)
        await r1.say(t="lobby", op="create", name="Night run", password="pw1", max=2, mode="circuit", city="Atlanta", laps=3)
        await asyncio.sleep(0.5)
        ll = r2.got(t="lobbies")[-1]["list"]
        mine = [x for x in ll if x["name"] == "Night run"]
        check(mine and mine[0]["locked"] and mine[0]["settings"]["city"] == "Atlanta" and mine[0]["n"] == 1, f"lobby list reaches others: {mine}")
        lid = mine[0]["id"]
        await r2.say(t="lobby", op="join", id=lid, password="nope"); await asyncio.sleep(0.1)
        check(any("Wrong password" in (m.get("text") or "") for m in r2.got(t="err")), "wrong password refused")
        await r2.say(t="lobby", op="join", id=lid, password="pw1"); await asyncio.sleep(0.1)
        await r3.say(t="lobby", op="join", id=lid, password="pw1"); await asyncio.sleep(0.1)
        check(any("full" in (m.get("text") or "") for m in r3.got(t="err")), "max players respected")
        await r1.say(t="lobby", op="start"); await asyncio.sleep(0.1)
        check(any("ready" in (m.get("text") or "") for m in r1.got(t="err")), "start waits for ready")
        await r2.say(t="lobby", op="ready", on=True); await asyncio.sleep(0.1)
        await r2.say(t="chat", ch="lobby", text="gl hf"); await asyncio.sleep(0.1)
        check(r1.got(t="chat", ch="lobby") and not r3.got(t="chat", ch="lobby"), "lobby chat to members only")
        await r1.say(t="lobby", op="start"); await asyncio.sleep(0.2)
        lm = r2.got(t="lobby")[-1]
        check(lm["state"] == "countdown" and lm["start_at"] > lm["now"] + 4 and lm["room"] == "race-" + lid, f"countdown with start time and race room: {lm['state']}")
        await asyncio.sleep(5.2)
        lm = r2.got(t="lobby")[-1]
        check(lm["state"] == "racing", "racing after the countdown")
        on = await (await sess.get(f"{H}/online")).json(); check(on["races"] == 1, "/online counts the race")
        await r1.say(t="lobby", op="result", ms=95000, pos=2); await r2.say(t="lobby", op="result", ms=93000, pos=1)
        await asyncio.sleep(0.6)
        res = r1.got(t="results")
        check(res and res[-1]["list"][0]["name"] == "Rita" and res[-1]["list"][0]["rank"] == 1, f"ranked results: {res[-1]['list'] if res else None}")
        check(r1.got(t="lobby")[-1]["state"] == "open", "back to the lobby after the race")
        lb = await (await sess.get(f"{H}/leaderboard?mode=circuit&city=Atlanta&track=&laps=3")).json()
        check(lb and lb[0]["name"] == "Rita" and lb[0]["ms"] == 93000, f"leaderboard {lb}")
        await r1.say(t="lobby", op="leave"); await asyncio.sleep(0.5)
        lm = r2.got(t="lobby")[-1]
        check(lm["host"] == r2.pid, "host leaves: the other member hosts")
        await r2.say(t="lobby", op="leave"); await asyncio.sleep(0.5)
        check(not [x for x in r3.got(t="lobbies")[-1]["list"] if x["id"] == lid], "empty lobby removed")

        # 10. same course: each member's game reports sameCourse + a course hash
        c1, c2 = P("Cy"), P("Di")
        for q in (c1, c2): await q.open(sess, base, lan=False)
        await asyncio.sleep(0.1)
        await c1.say(t="lobby", op="create", name="Seeded", mode="cruise"); await asyncio.sleep(0.5)
        lid = [x for x in c2.got(t="lobbies")[-1]["list"] if x["name"] == "Seeded"][0]["id"]
        await c2.say(t="lobby", op="join", id=lid); await c2.say(t="lobby", op="ready", on=True); await asyncio.sleep(0.1)
        await c1.say(t="lobby", op="course", same=True, check="abc"); await asyncio.sleep(0.1)
        check(not any(m["course"] for m in c1.got(t="lobby")[-1]["members"]), "course ignored before the race starts")
        await c1.say(t="lobby", op="start"); await asyncio.sleep(0.2)
        await c1.say(t="lobby", op="course", same=True, check="abc"); await c2.say(t="lobby", op="course", same=True, check="abd"); await asyncio.sleep(0.2)
        mem = {m["name"]: m["course"] for m in c1.got(t="lobby")[-1]["members"]}
        check(mem == {"Cy": {"same": True, "check": "abc"}, "Di": {"same": True, "check": "abd"}}, f"each member's course reaches the lobby: {mem}")

        # 11. voice through the relay ('VX' frames)
        v1, v2, v3 = P("Vic"), P("Val"), P("Vin")
        for q in (v1, v2, v3): await q.open(sess, base)
        await asyncio.sleep(0.15)
        for q in (v1, v2, v3): q.msgs.clear()
        def vx(q): return [f for f in q.msgs if isinstance(f, (bytes, bytearray)) and f[:2] == b"VX"]
        await v3.say(t="hear", on=False); await asyncio.sleep(0.05)
        for k in range(5): await v1.soc.send_bytes(b"VX" + bytes([0]) + b"opus" + bytes([k]))
        await v1.say(t="talk", ch="room", on=True)
        await asyncio.sleep(0.2)
        check(not vx(v2) and not vx(v3) and not v2.got(t="talk"), "no voice to the whole room (channel 0 and room 'talk' refused)")
        # crew radio: to crew mates in any room, not to others, not to a mate with hearing off
        await v1.say(t="crew", op="create", tag="VoxCrew"); await asyncio.sleep(0.1)
        v4 = P("Vox"); await v4.open(sess, base, room="faraway", lan=False); await asyncio.sleep(0.1)
        for q in (v2, v3, v4): await q.say(t="crew", op="join", tag="VoxCrew")
        await asyncio.sleep(0.15)
        for q in (v1, v2, v3, v4): q.msgs.clear()
        for k in range(3): await v1.soc.send_bytes(b"VX" + bytes([1]) + b"crew" + bytes([k]))
        await asyncio.sleep(0.2)
        got = vx(v4)
        check(len(got) == 3 and struct.unpack_from("<I", got[0], 3)[0] == v1.gid and got[0][2] == 1, "crew radio reaches a crew mate in another room, with the speaker's ghost id")
        check(vx(v2) and not vx(v3) and not vx(v1), "crew radio: crew mates yes, a mate with hearing off no, not back to the speaker")
        await v1.lan.send_bytes(ghst(v1.gid, 0.0, 0.0)); await v2.lan.send_bytes(ghst(v2.gid, 500.0, 0.0)); await asyncio.sleep(0.6)
        v2.msgs.clear()
        await v1.soc.send_bytes(b"VX" + bytes([2]) + b"near"); await asyncio.sleep(0.2)
        check(not vx(v2), "nearby voice: not to a player 500 m away")
        await v2.lan.send_bytes(ghst(v2.gid, 50.0, 0.0)); await asyncio.sleep(0.6)
        await v1.soc.send_bytes(b"VX" + bytes([2]) + b"near"); await asyncio.sleep(0.2)
        check(vx(v2), "nearby voice: to a player 50 m away")
        await sess.post(f"{H}/admin/mute", json={"pid": v1.pid, "minutes": 5}); await asyncio.sleep(2.1)
        v2.msgs.clear(); await v1.soc.send_bytes(b"VX" + bytes([0]) + b"muted"); await asyncio.sleep(0.2)
        check(not vx(v2), "a muted player's voice goes nowhere")

        # 12. class lock; the host leaving mid-race
        k1, k2, k3 = P("Kai"), P("Kim"), P("Kip")
        for q in (k1, k2, k3): await q.open(sess, base, lan=False)
        await asyncio.sleep(0.1)
        await k1.say(t="lobby", op="create", name="B only", cls="B"); await asyncio.sleep(0.5)
        lid = [x for x in k2.got(t="lobbies")[-1]["list"] if x["name"] == "B only"][0]["id"]
        check([x for x in k2.got(t="lobbies")[-1]["list"] if x["id"] == lid][0]["settings"]["cls"] == "B", "class lock in the lobby list")
        for q in (k2, k3): await q.say(t="lobby", op="join", id=lid)
        await k2.say(t="lobby", op="car", car="Jetta", cls="D"); await asyncio.sleep(0.1)
        await k2.say(t="lobby", op="ready", on=True); await asyncio.sleep(0.1)
        check(any("class B" in (m.get("text") or "") for m in k2.got(t="err")), "ready refused with a car of another class")
        await k2.say(t="lobby", op="car", car="GTO", cls="B"); await k2.say(t="lobby", op="ready", on=True)
        await k3.say(t="lobby", op="ready", on=True); await asyncio.sleep(0.1)
        lm = k1.got(t="lobby")[-1]
        check(all(m["ready"] for m in lm["members"] if m["pid"] != k1.pid) and [m for m in lm["members"] if m["pid"] == k2.pid][0]["cls"] == "B",
              "ready with the right class; car and class shown")
        await k1.say(t="lobby", op="start"); await asyncio.sleep(5.4)
        await k2.say(t="lobby", op="result", ms=60000, pos=1); await k3.say(t="lobby", op="result", ms=61000, pos=2); await asyncio.sleep(0.1)
        await k1.say(t="lobby", op="leave"); await asyncio.sleep(0.5)
        check(any("hosts the race now" in (m.get("text") or "") for m in k2.got(t="sys")), "host leaves mid-race: the others are told who hosts")
        check(k2.got(t="results") and k2.got(t="lobby")[-1]["host"] == k2.pid, "the race still ends with results for those left")

        # 13. reports
        x1, x2 = P("Rep"), P("Bad")
        await x1.open(sess, base); await x2.open(sess, base); await asyncio.sleep(0.1)
        for k in range(3):
            await x2.lan.send_bytes(ghst(x2.gid, 100.0 + k * 300, 0.0)); await asyncio.sleep(1.05)
        await x1.say(t="report", pid=x2.pid, why="cheating", text="teleporting around"); await asyncio.sleep(0.15)
        check(any("Report sent" in (m.get("text") or "") for m in x1.got(t="sys")), "report accepted")
        rr = await (await sess.get(f"{H}/admin/reports")).json()
        check(rr and rr[0]["about"] == x2.pid and rr[0]["why"] == "cheating" and len(rr[0]["trail"]) >= 3, f"report kept with the last positions: {rr[0]['trail'] if rr else None}")
        r = await sess.get(f"{H}/admin/reports?html=1"); txt = await r.text()
        check(r.status == 200 and "teleporting around" in txt, "reports page for the host")
        r = await sess.get(f"{H}/admin/reports", headers={"Cf-Connecting-Ip": "1.2.3.4"}); check(r.status == 403, "reports refused through the tunnel")

        # 14. meet-ups and the room list
        y1, y2, y3 = P("Mia"), P("Max"), P("Moe")
        await y1.open(sess, base); await y2.open(sess, base); await y3.open(sess, base, room="else", lan=False); await asyncio.sleep(0.1)
        await y1.lan.send_bytes(ghst(y1.gid, 12.0, 34.0)); await asyncio.sleep(0.1)
        await y1.say(t="meet", place="the pier", mins=10); await asyncio.sleep(0.15)
        mm = y2.got(t="meets")[-1]["list"]
        check(mm and mm[0]["place"] == "the pier" and abs(mm[0]["x"] - 12) < 0.1 and mm[0]["at"] > time.time() + 590, f"meet-up reaches the room, at my position: {mm}")
        check(y2.got(t="meet") and not y3.got(t="meet"), "only this room is told")
        mid = mm[0]["id"]
        await y2.say(t="meet", op="cancel", id=mid); await asyncio.sleep(0.1)
        check(y2.got(t="meets")[-1]["list"], "someone else can't cancel it")
        await y1.say(t="meet", op="cancel", id=mid); await asyncio.sleep(0.1)
        check(not y2.got(t="meets")[-1]["list"], "the poster can")
        await y1.say(t="rooms"); await asyncio.sleep(0.1)
        rl = {r["id"]: r["n"] for r in y1.got(t="rooms")[-1]["list"]}
        check(rl.get("mc3", 0) >= 2 and rl.get("else") == 1, f"room list with counts: {rl}")
    await srv.close()
    print("SUMMARY", "OK" if not fails else f"{fails} FAILED")

asyncio.run(main())

/* worker.js — MC3 multiplayer relay on Cloudflare Workers + Durable Objects.
 *
 * Production version of relay.py. One Durable Object per room (with WebSocket
 * Hibernation, so idle rooms cost nothing), plus a singleton Registry DO that
 * aggregates counts for /players. Same contract as relay.py; no game data ever
 * passes through it (PORT_PLAN.md s4).
 *
 *   WS  /lan?room=<id>&name=<n>   System Link tunnel (binary forward within room)
 *   WS  /roam?room=<id>&name=<n>  free-roam ghost snapshots
 *   GET /players[?rooms=a,b]      { players, online, roam, full, queue, roamBusy, rooms[] }
 *   GET /rooms                    [{ id, count, full, kind }]
 *   GET /                         health
 *
 * Deploy:  cd relay/cloudflare && npx wrangler deploy   (needs your Cloudflare login)
 */
const MAX_ROOM = 8;
const MAX_FRAME = 64 * 1024;
const RATE_BYTES = 1_000_000;
const RATE_MSGS = 400;
const CORS = { "Access-Control-Allow-Origin": "*" };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    if (p === "/lan" || p === "/roam") {
      const room = (url.searchParams.get("room") || "").slice(0, 64);
      if (!room) return new Response("room required", { status: 400 });
      // Optional origin allowlist for production (set ALLOWED_ORIGINS in wrangler vars).
      const allow = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
      if (allow.length && !allow.includes(request.headers.get("Origin") || ""))
        return new Response("origin not allowed", { status: 403 });
      return env.ROOM.get(env.ROOM.idFromName(room)).fetch(request);
    }
    if (p === "/players" || p === "/rooms")
      return env.REGISTRY.get(env.REGISTRY.idFromName("global")).fetch(request);
    if (p === "/") return new Response("mc3 relay (cloudflare) ok\n");
    return new Response("not found", { status: 404 });
  },
};

/* One instance per room id. */
export class Room {
  constructor(state, env) { this.state = state; this.env = env; }

  async fetch(request) {
    if (request.headers.get("Upgrade") !== "websocket")
      return new Response("expected websocket", { status: 426 });
    if (this.state.getWebSockets().length >= MAX_ROOM)
      return new Response("room full", { status: 409 });

    const url = new URL(request.url);
    const kind = url.pathname === "/roam" ? "roam" : "lan";
    const name = (url.searchParams.get("name") || "player").slice(0, 24);
    const room = (url.searchParams.get("room") || "").slice(0, 64);
    await this.state.storage.put("room", room);
    await this.state.storage.put("kind", kind);

    const [client, server] = Object.values(new WebSocketPair());
    this.state.acceptWebSocket(server);
    server.serializeAttachment({ kind, name });
    await this.report();
    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, message) {
    if (typeof message === "string") { if (message === "ping") ws.send("pong"); return; }
    if (message.byteLength > MAX_FRAME) return;
    const now = Date.now();
    let r = ws.deserializeAttachment() || {};
    if (!r.t || now - r.t >= 1000) { r.t = now; r.b = 0; r.m = 0; }
    r.b += message.byteLength; r.m += 1;
    ws.serializeAttachment(r);
    if (r.b > RATE_BYTES || r.m > RATE_MSGS) return;      // over the cap: drop
    for (const peer of this.state.getWebSockets()) {
      if (peer === ws) continue;
      try { peer.send(message); } catch (_) {}
    }
  }

  async webSocketClose(ws) { try { ws.close(); } catch (_) {} await this.report(); }
  async webSocketError(ws) { await this.report(); }

  async report() {
    const count = this.state.getWebSockets().length;
    const room = (await this.state.storage.get("room")) || "?";
    const kind = (await this.state.storage.get("kind")) || "lan";
    await this.env.REGISTRY.get(this.env.REGISTRY.idFromName("global"))
      .fetch("https://reg/update", { method: "POST", body: JSON.stringify({ room, count, kind }) });
  }
}

/* Singleton: aggregates room counts for /players and /rooms. */
export class Registry {
  constructor(state, env) {
    this.state = state;
    this.rooms = new Map();   // id -> { count, kind }
  }
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/update") {
      const { room, count, kind } = await request.json();
      if (count > 0) this.rooms.set(room, { count, kind }); else this.rooms.delete(room);
      return new Response("ok");
    }
    let list = [...this.rooms.entries()].map(([id, r]) =>
      ({ id, count: r.count, full: r.count >= MAX_ROOM, kind: r.kind }));
    const want = url.searchParams.get("rooms");
    if (want) { const ids = new Set(want.split(",")); list = list.filter(r => ids.has(r.id)); }
    if (url.pathname === "/rooms") return Response.json(list, { headers: CORS });
    const players = list.reduce((a, r) => a + r.count, 0);
    const roam = list.filter(r => r.kind === "roam").reduce((a, r) => a + r.count, 0);
    return Response.json({
      players, online: players, roam,
      full: list.filter(r => r.full).length, queue: 0, roamBusy: roam >= MAX_ROOM,
      rooms: list,
    }, { headers: { ...CORS, "Cache-Control": "no-store" } });
  }
}

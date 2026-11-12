# MC3 multiplayer relay

A game-agnostic binary WebSocket forwarder for the Midnight Club 3 web port. It
moves bytes between players in the same room and nothing else — **no game code
and no game data ever pass through it** (PORT_PLAN.md §4). Two builds, identical
contract:

| | `relay.py` (local / testing) | `cloudflare/` (production) |
|---|---|---|
| Stack | aiohttp | Workers + Durable Objects (one DO per room, WebSocket Hibernation) |
| Use | dev + the port session's game-side testing | public, off your home connection |

## Contract

- `WS /lan?room=<id>&name=<n>` — System Link tunnel: each binary frame is forwarded to the other members of the room.
- `WS /roam?room=<id>&name=<n>` — free-roam ghosts: same, for ~20 Hz car snapshots.
- `GET /players[?rooms=a,b]` — `{ players, online, roam, full, queue, roamBusy, rooms:[{id,count,full,kind}] }` (1 s cache).
- `GET /rooms` — `[{ id, count, full, kind }]`.
- `GET /` — health text.

Limits: **8 players/room** (matches MC3 System Link), **64 KB/frame**, per-socket
rate cap (~1 MB/s, 400 msgs/s). Measured car-sync is ~1 KB/s/player, well under.

## Run locally

```
pip install aiohttp
python relay.py --port 8090          # ws://127.0.0.1:8090/lan?room=<id>
python test_relay.py                 # the test suite (all green)
```

The game's page bridge connects to `ws://<host>:8090/lan?room=<id>`.

## Deploy to Cloudflare

```
cd cloudflare
npx wrangler deploy                  # uses your Cloudflare login
```

Gives `wss://mc3-relay.<your-subdomain>.workers.dev/lan?room=<id>`, or bind a
route like `relay.dubedition.xyz/*` (uncomment it in `wrangler.toml`). Point the
site's relay URL there. Rooms are free when idle (Hibernation); ~24 KB/s per full
8-player room.

## Scope

This repo is only the relay. The game-side (reading car state / tunnelling the
NvNet NIC's frames into these sockets) lives in the port build (`web_host.c`,
`mc3net`). The relay is deliberately dumb: it can't see the game, so cheating is
possible — fine for casual races; it has rate limits and an 8-player cap.

"""tools_city_routes.py: driving routes across all of San Diego for the test bots (relay/bots.py).

    python tools_city_routes.py [N=240] [out=relay/city_routes.json]

The roads come from the game's own HUD map (web/hudmap_sd.png, from hudmap.xbpf): the
grey/white road pixels are thinned to centre lines, and each route is a random drive along
them -- straight on at a junction where it can, never back the way it came -- about 1-2 km
long. Map pixel -> world, fitted 2026-11-11 so three streets recorded from the game's
traffic (ROUTES in bots.py) land on road pixels (98% of points):
    x = 399.3 + (px - 345) * 5.0      z = -31.1 - (py - 293) * 5.0
"""
import json, math, random, sys
import numpy as np
from PIL import Image
from skimage.morphology import skeletonize

N = int(sys.argv[1]) if len(sys.argv) > 1 else 240
OUT = sys.argv[2] if len(sys.argv) > 2 else "relay/city_routes.json"
X0, Z0, PX0, PY0, UPP = 399.3, -31.1, 345, 293, 5.0

im = np.asarray(Image.open("web/hudmap_sd.png").convert("RGB")).astype(int)
r, g, b = im[..., 0], im[..., 1], im[..., 2]
road = (r > 150) & (abs(r - b) < 25) & (abs(r - g) < 25)
skel = skeletonize(road)
H, W = skel.shape
NB = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]

def nbrs(x, y):
    return [(x + dx, y + dy) for dx, dy in NB if 0 <= x + dx < W and 0 <= y + dy < H and skel[y + dy, x + dx]]

# the biggest connected piece of the network (the mainland city), so no bot starts on an island
ys, xs = np.nonzero(skel)
seen, comps = set(), []
for p in zip(xs.tolist(), ys.tolist()):
    if p in seen: continue
    comp, stack = [], [p]; seen.add(p)
    while stack:
        q = stack.pop(); comp.append(q)
        for n in nbrs(*q):
            if n not in seen: seen.add(n); stack.append(n)
    comps.append(comp)
city = max(comps, key=len)
print(f"road centre-line pixels: {len(ys)}, pieces: {len(comps)}, city piece: {len(city)}")

def walk(rng, start, steps):
    path = [start]; prev = None; heading = None; visited = {start}
    for _ in range(steps):
        cur = path[-1]
        opts = [n for n in nbrs(*cur) if n != prev and n not in visited]
        if not opts: break
        if heading is not None:   # straight on where it can, sometimes a turn at a junction
            opts.sort(key=lambda n: -((n[0] - cur[0]) * heading[0] + (n[1] - cur[1]) * heading[1]))
            nxt = opts[0] if len(opts) == 1 or rng.random() < 0.8 else rng.choice(opts)
        else:
            nxt = rng.choice(opts)
        hx, hy = nxt[0] - cur[0], nxt[1] - cur[1]
        heading = (hx, hy) if heading is None else (0.7 * heading[0] + 0.3 * hx, 0.7 * heading[1] + 0.3 * hy)
        prev = cur; path.append(nxt); visited.add(nxt)
    return path

def simplify(path, tol=0.8):
    """Douglas-Peucker in pixels: corners only."""
    if len(path) < 3: return path
    (x0, y0), (x1, y1) = path[0], path[-1]
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    d = [abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / L for x, y in path[1:-1]]
    k = int(np.argmax(d)) + 1
    if d[k - 1] <= tol: return [path[0], path[-1]]
    return simplify(path[:k + 1], tol)[:-1] + simplify(path[k:], tol)

rng = random.Random(619)
routes = []
while len(routes) < N:
    p = walk(rng, rng.choice(city), 400)
    if len(p) < 150: continue                       # under ~750 m: try again
    pts = simplify(p)
    routes.append([(round(X0 + (x - PX0) * UPP, 1), round(Z0 - (y - PY0) * UPP, 1)) for x, y in pts])
lens = [sum(math.dist(a, b) for a, b in zip(rt, rt[1:])) for rt in routes]
json.dump({"note": "made by tools_city_routes.py from web/hudmap_sd.png; x z world units, road y = 0",
           "routes": routes}, open(OUT, "w"))
print(f"{len(routes)} routes, {min(lens):.0f}-{max(lens):.0f} units long, {sum(len(r) for r in routes)} corners -> {OUT}")

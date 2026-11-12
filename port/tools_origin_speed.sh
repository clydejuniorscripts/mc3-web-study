#!/bin/bash
# tools_origin_speed.sh [N=120] [P=8]: how fast the public site serves disc pieces that Cloudflare
# has NOT cached (they come from this PC through the tunnel, i.e. the home upload) -- what a
# first-time player far away gets. Random pieces of the biggest files, P at a time. Run in WSL.
N=${1:-120}; P=${2:-8}
cd /tmp || exit 1
V=$(curl -s http://127.0.0.1:8099/boot-profile.json | python3 -c 'import sys,json;print(json.load(sys.stdin)["v"])')
curl -s "http://127.0.0.1:8099/gc/$V/manifest.bin" > man.json
python3 - "$V" "$N" > urls.txt <<'EOF'
import json, random, sys, time
v, n = sys.argv[1], int(sys.argv[2])
man = json.load(open('man.json'))
big = sorted([f for f, s in man.items() if s > 30_000_000], key=lambda f: -man[f])[:8]
random.seed(time.time())
for _ in range(n):
    f = random.choice(big)
    print(f"https://game.dubedition.xyz/gc/{v}/{random.randrange(man[f] // 65536)}/{f}.bin")
EOF
S=$(date +%s.%N)
xargs -P "$P" -I{} curl -s -o /dev/null -D - -w 'size=%{size_download}\n' {} < urls.txt | grep -iE 'cf-cache|size=' > st.txt
E=$(date +%s.%N)
python3 - "$S" "$E" <<'EOF'
import sys
dt = float(sys.argv[2]) - float(sys.argv[1])
L = open('st.txt').read().splitlines()
b = sum(int(l.split('=')[1]) for l in L if l.startswith('size='))
s = {}
for l in L:
    if 'cf-cache' in l.lower():
        k = l.split(':')[1].strip(); s[k] = s.get(k, 0) + 1
print(f"{b/1e6:.1f} MB in {dt:.1f}s = {b/1e6/dt:.2f} MB/s; cache {s}")
EOF

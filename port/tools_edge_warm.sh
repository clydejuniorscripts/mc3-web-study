#!/bin/bash
# Pull every piece of the boot profile through the public address once, so Cloudflare's
# edge near the host has it before players ask. Prints the time and the cache statuses.
H=https://game.dubedition.xyz
T=$(mktemp -d)
curl -s $H/boot-profile.json > $T/p.json
python3 - "$T" "$H" <<'EOF'
import json,sys,urllib.parse
t,h=sys.argv[1],sys.argv[2]
p=json.load(open(t+"/p.json"))
with open(t+"/urls","w") as f:
    for path,i in p["chunks"]:
        f.write("%s/gc/%s/%d/%s.bin\n"%(h,p["v"],i,urllib.parse.quote(path)))
print(len(p["chunks"]),"pieces,",round(p["bytes"]/1e6,1),"MB, disc version",p["v"])
EOF
S=$(date +%s.%N)
xargs -P 8 -n 1 curl -s -o /dev/null -w "%{http_code} %{size_download} %header{cf-cache-status}\n" < $T/urls > $T/out 2>/dev/null
E=$(date +%s.%N)
awk '{n++; b+=$2; c[$1" "$3]++} END {printf "%d responses, %.1f MB\n", n, b/1e6; for (k in c) print "  " c[k] " x " k}' $T/out
python3 -c "print('seconds:', round($E-$S,1))"
rm -rf $T

#!/bin/bash
# Put race_seed.inc.c (the seeded random-race hook) into the engine tree, idempotent: the
# block between its >>> / <<< markers at the end of src/games/dub/recomp_manual.c, and its two
# exports in the web build's export list. Also takes out the one-off race trace block
# (race_trace.inc.c) if it is still installed. Remove the seed hook with --remove.
set -e
cd ~/mc3-web
M=src/games/dub/recomp_manual.c
SRC=/mnt/c/Games/mc3-web-port/race_seed.inc.c
bash /mnt/c/Games/mc3-web-port/install_race_trace.sh --remove >/dev/null
python3 - "$M" "$SRC" "${1:-}" <<'EOF'
import sys,re
m,src,mode=sys.argv[1],sys.argv[2],sys.argv[3]
t=open(m).read()
t=re.sub(r"\n*/\* >>> mc3-web-port: race seed.*?/\* <<< mc3-web-port: race seed \*/\n?","\n",t,flags=re.S)
if mode != "--remove":
    b=open(src).read().replace("\r\n","\n")
    t=t.rstrip("\n")+"\n\n"+b
open(m,"w").write(t.rstrip("\n")+"\n")
EOF
if [ "${1:-}" = "--remove" ]; then
  sed -i 's/,_web_race_seed_result//; s/,_web_race_seed//' CMakeLists.txt
else
  grep -q '_web_race_seed,' CMakeLists.txt || sed -i 's/,_web_mem_base/,_web_mem_base,_web_race_seed,_web_race_seed_result/' CMakeLists.txt
fi
echo "exports: $(grep -o '_web_race_seed[a-z_]*' CMakeLists.txt | tr '\n' ' ')"
echo "blocks: seed $(grep -c 'mc3-web-port: race seed' $M || true), trace $(grep -c 'mc3-web-port: race trace' $M || true)"

#!/bin/bash
# Put race_trace.inc.c (the one-off generator-finding instrumentation) into the engine tree,
# idempotent: the block between its >>> / <<< markers at the end of
# src/games/dub/recomp_manual.c, and web_race_trace in the web build's export list.
# Remove it again with: install_race_trace.sh --remove
set -e
cd ~/mc3-web
M=src/games/dub/recomp_manual.c
SRC=/mnt/c/Games/mc3-web-port/race_trace.inc.c
python3 - "$M" "$SRC" "${1:-}" <<'EOF'
import sys,re
m,src,mode=sys.argv[1],sys.argv[2],sys.argv[3]
t=open(m).read()
t=re.sub(r"\n*/\* >>> mc3-web-port: race trace.*?/\* <<< mc3-web-port: race trace \*/\n?","\n",t,flags=re.S)
if mode != "--remove":
    b=open(src).read().replace("\r\n","\n")
    t=t.rstrip("\n")+"\n\n"+b
open(m,"w").write(t.rstrip("\n")+"\n")
EOF
if [ "${1:-}" = "--remove" ]; then
  sed -i 's/,_web_race_trace//' CMakeLists.txt
else
  grep -q '_web_race_trace' CMakeLists.txt || sed -i 's/,_web_mem_base/,_web_mem_base,_web_race_trace/' CMakeLists.txt
fi
grep -c '_web_race_trace' CMakeLists.txt || true
grep -c 'mc3-web-port: race trace' $M || true

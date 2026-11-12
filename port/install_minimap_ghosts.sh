#!/bin/bash
# Put minimap_ghosts.inc.c into the engine tree (idempotent): the block between its
# >>> / <<< markers at the end of src/games/dub/recomp_manual.c, and the page's entry
# point in the web build's export list.
set -e
cd ~/mc3-web
M=src/games/dub/recomp_manual.c
SRC=/mnt/c/Games/mc3-web-port/minimap_ghosts.inc.c
python3 - "$M" "$SRC" <<'EOF'
import sys,re
m,src=sys.argv[1],sys.argv[2]
t=open(m).read(); b=open(src).read().replace("\r\n","\n")
t=re.sub(r"\n*/\* >>> mc3-web-port: minimap ghosts.*?/\* <<< mc3-web-port: minimap ghosts \*/\n?","\n",t,flags=re.S)
open(m,"w").write(t.rstrip("\n")+"\n\n"+b)
EOF
grep -q '_web_ghost_table' CMakeLists.txt || sed -i 's/,_web_mem_base/,_web_mem_base,_web_ghost_table/' CMakeLists.txt
grep -c '_web_ghost_table' CMakeLists.txt
grep -n 'g_ebx\|g_ebp' work-dub/gen/recomp_types.h | head -4
tail -3 $M

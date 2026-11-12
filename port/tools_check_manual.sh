#!/bin/bash
# Install the hooks and compile just recomp_manual.c (a syntax check before a long relift/build).
source ~/emsdk/emsdk_env.sh >/dev/null 2>&1
cd ~/mc3-web || exit 1
bash /mnt/c/Games/mc3-web-port/install_minimap_ghosts.sh >/dev/null
B=work-dub/build-web
t=$(ninja -C $B -t targets all | grep 'recomp_manual.c.o' | head -1 | cut -d: -f1)
echo "target: $t"
ninja -C $B "$t" 2>&1 | grep -E "error|warning: (implicit|incompatible)|FAILED|ninja:" | head -40
echo "exit ${PIPESTATUS[0]}"

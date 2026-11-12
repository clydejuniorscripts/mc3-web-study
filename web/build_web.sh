#!/bin/bash
# Build the WebAssembly version into work-dub/build-web (mcdub3.js/.wasm).
set -eo pipefail
source "${EMSDK:-$HOME/emsdk}/emsdk_env.sh" >/dev/null 2>&1   # emsdk 4.x or newer (built with 7.0.0)
cd "$(dirname "$0")/.."   # the repository root
B=work-dub/build-web
mkdir -p $B
# The file list of the player's extracted disc (names and sizes only). The
# hard-disk folders a native run writes into game/ (TDATA, UDATA, CACHE) are
# player data, not the disc: the browser mounts writable ones there.
( cd game && find . -type f -printf '%P\t%s\n' | grep -viE '^(TDATA|UDATA|CACHE)/' | sort ) > $B/game_manifest.txt
echo "manifest: $(wc -l < $B/game_manifest.txt) files"
emcmake cmake -S . -B $B -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DMC3_NATIVE_BINK=ON -DMC3_VULKAN=OFF -DMC3_GEN_OPT=${GEN_OPT:--O2} \
  -DCMAKE_C_FLAGS="-pthread -matomics -mbulk-memory" > $B/configure.log 2>&1 || { tail -40 $B/configure.log; exit 1; }
set +e
ninja -C $B -j${JOBS:-8} -k 0 ${TARGET:-} > $B/build.log 2>&1
rc=$?
grep -E "error:|FAILED:|undefined symbol" $B/build.log | sort | uniq -c | sort -rn | head -${SHOW:-60}
echo "ninja exit $rc"
ls -la $B/mcdub3.js $B/mcdub3.wasm 2>/dev/null

#!/bin/bash
# tools_calls.sh <hexva>...   only the call instructions of each function, in order
cd ~/mc3-web || exit 1
T=/mnt/c/Games/mc3-web-port/tools_re3.py
for f in "$@"; do echo "===== $f"; python3 $T info $f | head -2 | cut -c1-400; python3 $T asm $f 2500 | grep -v '^ *;' | cut -c3-13,38-110 | grep -n -E 'call |ret' ; done

#!/bin/bash
# tools_fn.sh <hexva>...   which function each address is in
cd ~/mc3-web || exit 1
for a in "$@"; do printf "%s  " "$a"; python3 /mnt/c/Games/mc3-web-port/tools_re2.py fn "$a"; done

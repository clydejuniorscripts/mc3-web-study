#!/bin/bash
# tools_pgrep.sh <file under ~/mc3-web> [context]   grep with the regex in /mnt/c/Games/mc3-web-port/pat.txt
# (the pattern lives in a file because wsl mangles ( | and $ in arguments)
cd ~/mc3-web || exit 1
grep -n -E -C "${2:-0}" -f /mnt/c/Games/mc3-web-port/pat.txt "$1" | cut -c1-220

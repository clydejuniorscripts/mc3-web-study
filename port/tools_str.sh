#!/bin/bash
# tools_str.sh   strings matching the regex in /mnt/c/Games/mc3-web-port/pat.txt, and who references them
cd ~/mc3-web || exit 1
python3 /mnt/c/Games/mc3-web-port/tools_re2.py str "$(cat /mnt/c/Games/mc3-web-port/pat.txt)"

#!/bin/bash
# tools_w.sh <re2|re3> args...   run an RE helper inside ~/mc3-web
cd ~/mc3-web || exit 1
t=$1; shift
python3 /mnt/c/Games/mc3-web-port/tools_$t.py "$@"

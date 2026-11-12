#!/bin/bash
# Rebuild the WebAssembly game from the current ~/mc3-web tree, then save
# the port's diff and web files to C:\Games\mc3-web-port.
set -o pipefail
source ~/emsdk/emsdk_env.sh >/dev/null 2>&1
cd ~/mc3-web
cp /mnt/c/Games/mc3-web-port/web/{web_host.c,serve.py,index.html,build_web.sh,pre.js} web/ 2>/dev/null
mkdir -p web/disc && cp /mnt/c/Games/mc3-web-port/web/disc/*.js web/disc/
cp /mnt/c/Games/mc3-web-port/nvnet.c xboxrecomp/src/usb/nvnet.c 2>/dev/null   # NvNet NIC model
JOBS=${JOBS:-6} SHOW=${SHOW:-30} bash web/build_web.sh
bash /mnt/c/Games/mc3-web-port/save_patch.sh >/dev/null 2>&1

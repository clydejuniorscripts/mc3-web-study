#!/bin/bash
cd ~/mc3-web
git diff > web/web-port.patch
mkdir -p "/mnt/c/Games/mc3-web-port/web"
cp web/*.c web/*.py web/*.html web/*.sh web/web-port.patch "/mnt/c/Games/mc3-web-port/web/" 2>/dev/null
git diff --stat | tail -3
ls web

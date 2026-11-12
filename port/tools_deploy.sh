#!/bin/bash
# Copy the page and server to the running tree; restart the game server if serve.py changed.
set -e
S=/mnt/c/Games/mc3-web-port/web; D=~/mc3-web/web
cp $S/index.html $D/index.html
cp $S/social.js $D/social.js            # chat, crews and voice (relay/social.py)
mkdir -p $D/fonts && cp -u $S/fonts/*.woff2 $D/fonts/ 2>/dev/null || true   # page fonts
mkdir -p $D/flags && cp -u $S/flags/*.png $D/flags/ 2>/dev/null || true   # country flags for the name tags
if ! cmp -s $S/serve.py $D/serve.py; then
  cp $S/serve.py $D/serve.py
  pkill -9 -f "web/serve.py" || true
  echo "serve.py updated; server restarting"
  for i in 1 2 3 4 5 6 7 8 9 10; do sleep 1; curl -s -o /dev/null -m 2 http://127.0.0.1:8099/engine.json && break; done
fi
curl -s -m 5 http://127.0.0.1:8099/engine.json; echo
curl -s -m 5 http://127.0.0.1:8099/ | grep -c 'id="boot"'

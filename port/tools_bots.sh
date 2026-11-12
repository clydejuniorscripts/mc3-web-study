#!/bin/bash
# tools_bots.sh start [N] [STILL] | stop | status   -- the relay's test bots (relay/bots.py), in WSL; STILL: the first STILL bots stand still.
# Bots join send-only (listen=0), so N can be large (200 for a stress test).
cd ~/mc3-web || exit 1
B=/mnt/c/Games/mc3-web-port/relay/bots.py
pids() { pgrep -f "python3 $B" | grep -v "^$$\$"; }
case "$1" in
  start)
    for p in $(pids); do kill "$p"; done; sleep 1
    rm -f /mnt/c/Games/mc3-web-port/relay/bots.off
    nohup work-dub/venv/bin/python3 "$B" --n "${2:-3}" ${3:+--still $3} ${4:+--park $4} ${BOTS_ARGS:-} > /tmp/bots.log 2>&1 < /dev/null &
    sleep 8 ;;
  stop)
    touch /mnt/c/Games/mc3-web-port/relay/bots.off; sleep 2
    for p in $(pids); do kill "$p"; done ;;
esac
echo "bots running: $(pids | wc -l) process(es), joined: $(grep -c 'in room' /tmp/bots.log 2>/dev/null)"
grep -v 'in room' /tmp/bots.log 2>/dev/null | tail -3
curl -s http://127.0.0.1:8090/players; echo

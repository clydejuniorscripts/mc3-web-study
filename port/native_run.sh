#!/bin/bash
# Run the native reference for a while; summarise how far it got.
cd ~/mc3-web
mkdir -p work-dub/save-native
export MC3_SAVE_DIR=$PWD/work-dub/save-native
export RECOMP_AUDIO=${RECOMP_AUDIO:-0}
export SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-dummy}
LOG=work-dub/native-run-${RECOMP_AUDIO}.log
timeout ${SECS:-70} xvfb-run -a -s "-screen 0 1280x720x24" ./work-dub/build-linux/mcdub3 > $LOG 2>&1
echo "exit $? (124 = still running at the timeout)"
grep -E "PATH\].*\.bik|BINK\]|ICALL\]|hitch\] frame|FATAL|CRASH" $LOG | tail -25
grep -c "" $LOG

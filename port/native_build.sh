#!/bin/bash
# Native Linux build of the same lift (the reference the web build is compared with).
cd ~/mc3-web
JOBS=8 bash tools/build_linux.sh > work-dub/native-build.log 2>&1
echo "exit $?"
tail -5 work-dub/native-build.log
ls -la work-dub/build-linux*/mcdub3 2>/dev/null

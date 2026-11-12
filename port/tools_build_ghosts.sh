#!/bin/bash
# Install the minimap hook, relift (the set of overrides changed) and rebuild the web
# engine. Players are on the pinned copy (work-dub/build-web-live), so a build here
# reaches nobody until tools_pin.sh new; try it on the site with ?ENGINE=next.
#   NORELIFT=1  skip the relift (only the hook's body changed)
cd ~/mc3-web || exit 1
bash /mnt/c/Games/mc3-web-port/install_minimap_ghosts.sh >/dev/null
if [ "${NORELIFT:-0}" != "1" ]; then
  date +"relift start %T"
  LIFT_ONLY=1 bash tools/regen.sh > work-dub/logs/relift_ghosts.log 2>&1
  echo "relift exit $?"; tail -2 work-dub/logs/relift_ghosts.log
  grep -E 'sub_000B0A50|sub_00079C30|sub_00079B40|sub_00203C80|sub_00202F30|sub_0006DFB0' work-dub/gen/.manual_overrides
  grep -l 'void sub_000B0A50_gen(void)' work-dub/gen/recomp_*.c
  grep -c 'void sub_000AE9E0(void)' work-dub/gen/recomp_*.c | head -3
fi
date +"build start %T"
JOBS=${JOBS:-6} SHOW=30 bash web/build_web.sh
date +"build end %T"
grep -c web_ghost_table work-dub/build-web/mcdub3.js

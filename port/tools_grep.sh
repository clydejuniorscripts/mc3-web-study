#!/bin/bash
# tools_grep.sh <lo> <hi> <regex>   grep the .text disassembly between two addresses (hex, no 0x)
python3 - "$@" <<'PY'
import re,sys,os
lo,hi=int(sys.argv[1],16),int(sys.argv[2],16); rx=re.compile(sys.argv[3])
for l in open(os.path.expanduser("~/mc3-web/work-dub/analysis/disasm/asm/text.asm"),errors="replace"):
    if l.startswith("  0x"):
        a=int(l[4:12],16)
        if lo<=a<hi and rx.search(l): print(l[2:12],l[40:110].rstrip())
PY

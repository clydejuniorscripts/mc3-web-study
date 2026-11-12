#!/bin/bash
# tools_asm.sh <hex> [<hex> ...]   the raw disassembly of each function (from its label to its end), int3 padding left out.
A=~/mc3-web/work-dub/analysis/disasm/asm/text.asm
for f in "$@"; do
  f=$(printf '%08X' "0x${f#sub_}")
  echo "== sub_$f"
  awk -v F="sub_$f:" '$1 == F {p = 1} p {print} p && /^; end of function/ {exit}' "$A" | grep '0x00' | grep -v int3
done

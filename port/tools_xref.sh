#!/bin/bash
# tools_xref.sh <hex VA> [...]   code that pushes or loads this address (an immediate operand), with the function each sits in.
A=~/mc3-web/work-dub/analysis/disasm/asm/text.asm
for v in "$@"; do
  v=$(printf '0x%x' "0x${v#0x}")
  echo "== $v"
  grep -n -E "(push|mov|lea|cmp) +[^;]*\b$v\b" "$A" | head -20 | while IFS= read -r line; do
    a=$(echo "$line" | grep -o -E '0x00[0-9A-F]{6}' | head -1)
    f=$(python3 /mnt/c/Games/mc3-web-port/tools_fnat.py "${a#0x}" | head -1)
    echo "  $f :: $(echo "$line" | cut -d: -f2- | sed -E 's/ +/ /g' | cut -c1-90)"
  done
done

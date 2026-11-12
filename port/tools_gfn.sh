#!/bin/bash
# tools_gfn.sh <sub_XXXXXXXX> [all]   a generated function, compact: labels, calls (as CALL addr),
#   memory reads/writes and compares; flag bookkeeping and leaf register shuffles left out.
#   "all" keeps every line. Searches ~/mc3-web/work-dub/gen/*.c (the _gen body if overridden).
cd ~/mc3-web/work-dub/gen || exit 1
fn="$1"
f=$(grep -l "^void ${fn}\(_gen\)\?(void)$" *.c | head -1)
[ -z "$f" ] && { echo "not found: $fn"; exit 1; }
echo "== $fn in $f"
awk -v fn="$fn" '$0 ~ "^void " fn "(_gen)?\\(void\\)$" {p=1} p {print} p && /^}$/ {exit}' "$f" |
if [ "$2" = "all" ]; then cat; else
  grep -vE '^\s*_fa|^\s*_fas|g_seh_ebp = ebp|frame stays current|^\s*$|\(void\)_f|int _flags|uint32_t _fa|int32_t _fas' |
  sed -E 's/PUSH32\(esp, (0x[0-9A-F]+)u\); recomp_leaf.*RECOMP_ABI_CALL\((0x[0-9A-F]+)u[^;]*;.*/CALL \2/; s/recomp_leaf_(st|ld)_[a-z]+\(g?_?[a-z]*\);? ?//g' |
  cut -c1-150
fi

#!/bin/bash
# tools_gen.sh <sub_XXXXXXXX> [lines]   show the generated C of a recompiled function
cd ~/mc3-web/work-dub/gen || exit 1
python3 - "$1" "${2:-80}" <<'PY'
import sys,glob,re
fn,n=sys.argv[1],int(sys.argv[2])
rx=re.compile(r"^void %s(_gen)?\(void\)\s*$"%fn)
for p in sorted(glob.glob("recomp_*.c")):
    L=open(p,errors="replace").read().split("\n")
    for i,l in enumerate(L):
        if rx.match(l):
            print("==",p,i+1)
            for k in L[i:i+n]:
                print(k)
                if k.startswith("}"): break
            sys.exit(0)
print("not found")
PY

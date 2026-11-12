#!/usr/bin/env python3
"""tools_re3.py info <hexva>...   : function bounds, callers, callees
   tools_re3.py asm <hexva> [n]   : disassembly of the function containing va (n lines max)
   tools_re3.py range <lo> <hi>   : list functions in [lo,hi) with sizes and caller counts
"""
import json, sys, os, bisect, re, subprocess
A = os.path.expanduser("~/mc3-web/work-dub/analysis/disasm/")
F = json.load(open(A + "functions.json"))
FL = sorted((int(f["start"], 16), int(f["end"], 16), f) for f in F)
def fn_of(va):
    i = bisect.bisect_right(FL, (va, 1 << 40, {})) - 1
    if i >= 0 and FL[i][0] <= va < max(FL[i][1], FL[i][0] + 1): return FL[i]
    return None
def name(va):
    f = fn_of(va); return "%s" % f[2]["name"] if f else "?%08X" % va
c = sys.argv[1]
if c == "info":
    for a in sys.argv[2:]:
        f = fn_of(int(a, 16))
        if not f: print(a, "no function"); continue
        d = f[2]
        print("%s  %08X-%08X size %d" % (d["name"], f[0], f[1], d["size"]))
        print("   called_by:", " ".join(sorted(set(name(int(x, 16)) for x in d["called_by"]))))
        print("   calls_to :", " ".join(sorted(set(name(int(x, 16)) for x in d["calls_to"]))))
elif c == "range":
    lo, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
    for s, e, d in FL:
        if lo <= s < hi: print("%08X size %5d  callers %3d  calls %3d" % (s, d["size"], len(d["called_by"]), len(d["calls_to"])))
elif c == "asm":
    va = int(sys.argv[2], 16); n = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    f = fn_of(va); lo, hi = (f[0], f[1]) if f else (va, va + 0x200)
    # find in .text.asm by address prefix
    path = A + "asm/"
    files = [p for p in os.listdir(path) if p.startswith(".text") or p.startswith("text")]
    out = 0
    for p in files:
        with open(path + p, errors="replace") as fh:
            on = False
            for line in fh:
                m = re.match(r"\s*(?:0x)?([0-9A-Fa-f]{8})[:\s]", line)
                if m:
                    a = int(m.group(1), 16)
                    on = lo <= a < hi
                if on:
                    sys.stdout.write(line); out += 1
                    if out >= n: sys.exit(0)
    if not out: print("no asm found; files:", os.listdir(path)[:40])

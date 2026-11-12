#!/usr/bin/env python3
"""RE helper: strings -> xrefs -> functions, for the recompiled MC3 tree.
usage: tools_re2.py fmt | str <regex> | xref <hexva> | fn <hexva>
"""
import json, re, sys, os, bisect
A = os.path.expanduser("~/mc3-web/work-dub/analysis/disasm/")
def load(n):
    with open(A + n) as f: return json.load(f)

def fmt():
    for n in ("strings.json", "xrefs.json", "functions.json", "labels.json"):
        d = load(n)
        print("==", n, type(d).__name__, len(d))
        if isinstance(d, dict):
            for k in list(d)[:3]:
                v = d[k]; s = json.dumps(v)
                print("  ", k, "->", s[:400])
        else:
            for v in d[:3]: print("  ", json.dumps(v)[:400])

_fn = None
def funcs():
    global _fn
    if _fn is None:
        d = load("functions.json")
        items = d if isinstance(d, list) else list(d.values())
        fl = []
        for f in items:
            a = f.get("address") or f.get("start") or f.get("addr")
            if isinstance(a, str): a = int(a, 16)
            e = f.get("end") or (a + (f.get("size") or 0))
            if isinstance(e, str): e = int(e, 16)
            fl.append((a, e, f.get("name", "")))
        fl.sort()
        _fn = fl
    return _fn
def fn_of(va):
    fl = funcs(); i = bisect.bisect_right(fl, (va, 1 << 40, "")) - 1
    if i >= 0 and fl[i][0] <= va < max(fl[i][1], fl[i][0] + 1): return fl[i]
    return None

def strs(rx):
    d = load("strings.json"); r = re.compile(rx, re.I)
    items = d if isinstance(d, list) else [dict(v, _k=k) if isinstance(v, dict) else {"_k": k, "value": v} for k, v in d.items()]
    out = []
    for s in items:
        t = s.get("value") or s.get("string") or s.get("text") or ""
        if r.search(t):
            a = s.get("address") or s.get("addr") or s.get("_k")
            if isinstance(a, str): a = int(a, 16)
            out.append((a, t))
    return out

_x = None
def xrefs_to(va):
    global _x
    if _x is None: _x = load("xrefs.json")
    d = _x; out = []
    items = d if isinstance(d, list) else d.get("xrefs", d)
    if isinstance(items, dict):
        for k in (hex(va), "0x%08x" % va, "0x%08X" % va, str(va)):
            if k in items: return [items[k]]
        return []
    for x in items:
        t = x.get("to") if "to" in x else x.get("target")
        if isinstance(t, str): t = int(t, 16)
        if t == va: out.append(x)
    return out

if __name__ == "__main__":
    c = sys.argv[1]
    if c == "fmt": fmt()
    elif c == "str":
        for a, t in strs(sys.argv[2]):
            refs = xrefs_to(a)
            print("%08X %r" % (a, t[:90]))
            for x in refs[:12]:
                f = x.get("from") if isinstance(x, dict) else x
                if isinstance(f, str): f = int(f, 16)
                fn = fn_of(f) if isinstance(f, int) else None
                print("     <- %s  in %s" % (("%08X" % f) if isinstance(f, int) else json.dumps(x)[:200], ("%s@%08X" % (fn[2], fn[0])) if fn else "?"))
    elif c == "xref":
        va = int(sys.argv[2], 16)
        for x in xrefs_to(va):
            f = x.get("from") if isinstance(x, dict) else x
            if isinstance(f, str): f = int(f, 16)
            fn = fn_of(f) if isinstance(f, int) else None
            print("  <- %s %s in %s" % (("%08X" % f) if isinstance(f, int) else "?", x.get("type", "") if isinstance(x, dict) else "", ("%s@%08X" % (fn[2], fn[0])) if fn else "?"))
    elif c == "fn":
        print(fn_of(int(sys.argv[2], 16)))

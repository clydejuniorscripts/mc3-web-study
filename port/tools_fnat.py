"""tools_fnat.py <hex> [<hex> ...]: which function each code address sits in (from the .text disassembly),
with the instructions around it.  python3 tools_fnat.py 188157 296465"""
import os, re, sys
asm = os.path.expanduser('~/mc3-web/work-dub/analysis/disasm/asm/text.asm')
want = sorted(int(a, 16) for a in sys.argv[1:])
lab = re.compile(r'^sub_([0-9A-F]{8}):')
ins = re.compile(r'^  0x([0-9A-F]{8})\s+\S+\s+(.*)$')
cur, ring, out, i = None, [], {}, 0
for l in open(asm, errors='replace'):
    m = lab.match(l)
    if m: cur = m.group(1); continue
    m = ins.match(l)
    if not m: continue
    a = int(m.group(1), 16)
    ring = (ring + ['%08X %s' % (a, m.group(2).strip())])[-6:]
    while i < len(want) and a >= want[i]:
        out[want[i]] = (cur, list(ring)); i += 1
    if i == len(want): break
for w in want:
    f, r = out.get(w, (None, []))
    print('%08X in sub_%s' % (w, f)); print('   ' + '\n   '.join(r))

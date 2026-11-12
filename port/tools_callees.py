"""tools_callees.py: the calls a function makes (from the .text disassembly), down to a depth,
marking the functions that advance rand()'s state (0x47C390).
  python3 tools_callees.py <hex fn> [depth]
"""
import os, re, sys, glob

asm = os.path.expanduser('~/mc3-web/work-dub/analysis/disasm/asm/text.asm')
lab_rx = re.compile(r'^sub_([0-9A-F]{8}):'); call_rx = re.compile(r'-> sub_([0-9A-F]{8})\s*$')
calls, cur = {}, None
for l in open(asm, errors='replace'):
    m = lab_rx.match(l)
    if m: cur = int(m.group(1), 16); calls.setdefault(cur, []); continue
    if cur is not None and l.startswith('  0x'):
        m = call_rx.search(l)
        if m: calls[cur].append(int(m.group(1), 16))
rand = set()
fn_rx = re.compile(r'^void sub_([0-9A-F]{8})(_gen)?\(void\)')
for path in glob.glob(os.path.expanduser('~/mc3-web/work-dub/gen/recomp_*.c')):
    fn = None
    for line in open(path, errors='replace'):
        m = fn_rx.match(line)
        if m: fn = int(m.group(1), 16); continue
        if fn is not None and 'MEM32(0x47C390) =' in line: rand.add(fn)
def reaches(f, d, seen):
    if f in rand: return True
    if d == 0 or f in seen: return False
    seen.add(f)
    return any(reaches(c, d - 1, seen) for c in calls.get(f, []))
def show(f, d, ind, seen):
    tag = ' RAND' if f in rand else (' (reaches rand)' if reaches(f, 6, set()) else '')
    print('  ' * ind + 'sub_%08X%s' % (f, tag))
    if d == 0 or f in seen: return
    seen.add(f)
    for c in dict.fromkeys(calls.get(f, [])): show(c, d - 1, ind + 1, seen)
if __name__ == '__main__':
    root = int(sys.argv[1], 16); depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    show(root, depth, 0, set())

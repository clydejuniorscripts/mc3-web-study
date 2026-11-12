"""tools_callers.py: who calls these functions (from the .text disassembly), with the caller
function each call sits in.  python3 tools_callers.py <hex> [<hex> ...] [--in lo hi]
"""
import bisect, os, re, sys

args = sys.argv[1:]
lo, hi = 0, 1 << 32
if '--in' in args:
    i = args.index('--in'); lo, hi = int(args[i + 1], 16), int(args[i + 2], 16); args = args[:i]
want = {int(a, 16) for a in args}
asm = os.path.expanduser('~/mc3-web/work-dub/analysis/disasm/asm/text.asm')
call_rx = re.compile(r'-> sub_([0-9A-F]{8})\s*$')
lab_rx = re.compile(r'^sub_([0-9A-F]{8})')
starts, calls = [], []
for l in open(asm, errors='replace'):
    m = lab_rx.match(l)
    if m:
        starts.append(int(m.group(1), 16)); continue
    if l.startswith('  0x'):
        m = call_rx.search(l)
        if m and int(m.group(1), 16) in want:
            calls.append((int(l[4:12], 16), int(m.group(1), 16)))
starts.sort()
for at, tgt in calls:
    if not (lo <= at < hi): continue
    k = bisect.bisect_right(starts, at) - 1
    fn = 'sub_%08X' % starts[k] if k >= 0 else '?'
    print('%08X calls sub_%08X  (in %s)' % (at, tgt, fn))

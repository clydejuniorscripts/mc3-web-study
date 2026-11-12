"""tools_grepfn.py <regex> [lo hi]: instructions matching a regex, with the function each sits in,
optionally only between code addresses lo..hi (hex).   python3 tools_grepfn.py 'mov +dword ptr \\[e..\\s\\+ 0xc\\],' 198000 19A000"""
import os, re, sys
asm = os.path.expanduser('~/mc3-web/work-dub/analysis/disasm/asm/text.asm')
rx = re.compile(sys.argv[1])
lo = int(sys.argv[2], 16) if len(sys.argv) > 3 else 0
hi = int(sys.argv[3], 16) if len(sys.argv) > 3 else 1 << 32
lab = re.compile(r'^sub_([0-9A-F]{8}):')
ins = re.compile(r'^  0x([0-9A-F]{8})\s+\S+\s+(.*)$')
cur = None
for l in open(asm, errors='replace'):
    m = lab.match(l)
    if m: cur = m.group(1); continue
    m = ins.match(l)
    if not m: continue
    a = int(m.group(1), 16)
    if lo <= a < hi and rx.search(m.group(2)):
        print('%08X sub_%s  %s' % (a, cur, m.group(2).strip()[:90]))

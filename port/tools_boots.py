"""tools_boots.py [N] [all]   the last N visits' reports from the game server (/dev/boots), readable.
   Leaves out the noise (Mirror/UNIMPL/FILE failures, ordinary slow frames)."""
import json, sys, re, datetime, urllib.request
n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
allx = 'all' in sys.argv
d = json.load(urllib.request.urlopen('http://127.0.0.1:8099/dev/boots'))
skip = re.compile(r"Mirror \d+: FAILED|UNIMPL|\[FILE\] -> 0xC0000034|stat=0|read 4: XBEH|tiled aperture")
H = re.compile(r"\[hitch\] frame (\d+): (\d+) ms")
for vid, v in [kv for kv in d if kv[0] != 'selftest'][-n:]:
    L = v['lines']
    print('==', vid, v['via'], datetime.datetime.fromtimestamp(v['first']).strftime('%H:%M:%S'), '-',
          datetime.datetime.fromtimestamp(v['last']).strftime('%H:%M:%S'), len(L), 'lines, snapshots', len(v.get('snapshots', [])))
    hs = []
    for t, line, ms, hid in L:
        m = H.search(line)
        if m:
            hs.append((t / 1000, int(m.group(1)), int(m.group(2))))
            if not allx: continue
        if skip.search(line) and not allx: continue
        print('  %7.1fs %s%s' % (t / 1000, line[:150].strip(), ' HID' if hid else ''))
    if hs:
        print('  slow frames: %d, worst %d ms; by 10 s: %s' % (len(hs), max(h[2] for h in hs),
              ' '.join('%ds:%dms' % (k, max(h[2] for h in hs if int(h[0] // 10 * 10) == k)) for k in sorted({int(h[0] // 10 * 10) for h in hs}))))

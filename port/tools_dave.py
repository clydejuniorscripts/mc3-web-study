#!/usr/bin/env python3
"""tools_dave.py -- list / extract files from MC3's 'Dave' archives (assets_x.dat).

  python3 tools_dave.py list    <assets_x.dat> [regex]
  python3 tools_dave.py extract <assets_x.dat> <regex> <outdir>

Format (read from default.xbe sub_00286790 / sub_00285B90):
  "Dave", u32 count, u32 tocSize, u32 namesSize; TOC at 0x800: count x {nameOff, dataOff,
  size, zsize}; names at 0x800 + tocSize, sorted, packed as an LSB-first stream of 6-bit
  indices into " #$()-./?0123456789_abcdefghijklmnopqrstuvwxyz~" (0 ends the name). A name
  whose first value is >= 0x38 shares a prefix with the previous entry: prefix length =
  (v0 - 0x38) | (v1 & 3) << 3 | (v1 >> 2 & 7) << 5, and its own characters start at value 2.
  Data: raw deflate when zsize != size.
"""
import re, struct, sys, zlib, os

TBL = "\0 #$()-./?0123456789_abcdefghijklmnopqrstuvwxyz~"


def vals(buf, off):
    acc = nb = 0
    while True:
        while nb < 6:
            acc |= buf[off] << nb; off += 1; nb += 8
        yield acc & 63
        acc >>= 6; nb -= 6


def read(path):
    f = open(path, 'rb'); h = f.read(16)
    assert h[:4] in (b'Dave', b'DAVE'), h[:4]
    n, toc, nsz = struct.unpack_from('<3I', h, 4)
    f.seek(0x800); t = f.read(toc); names = f.read(nsz)
    packed = h[:4] == b'Dave'
    out, prev = [], ''
    for i in range(n):
        no, do, sz, zs = struct.unpack_from('<4I', t, i * 16)
        if packed:
            g = vals(names, no); v0 = next(g)
            if v0 >= 0x38:
                v1 = next(g); pl = (v0 - 0x38) | (v1 & 3) << 3 | (v1 >> 2 & 7) << 5
                s = prev[:pl]
            elif v0 == 0 or v0 >= len(TBL):
                out.append(('', do, sz, zs)); prev = ''; continue
            else:
                s = TBL[v0]
            for v in g:
                if v == 0 or v >= len(TBL): break
                s += TBL[v]
        else:
            e = names.index(b'\0', no); s = names[no:e].decode('latin1')
        out.append((s, do, sz, zs)); prev = s
    return f, out


def data(f, do, sz, zs):
    f.seek(do); b = f.read(zs)
    return b if zs == sz else zlib.decompress(b, -15)


if __name__ == '__main__':
    cmd, path = sys.argv[1], sys.argv[2]
    f, ents = read(path)
    rx = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
    for s, do, sz, zs in ents:
        if rx and not rx.search(s): continue
        if cmd == 'list': print(f'{sz:9d} {zs:9d} {s}')
        elif cmd == 'extract' and not s.endswith('/'):
            p = os.path.join(sys.argv[4], s.lstrip('/')); os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
            open(p, 'wb').write(data(f, do, sz, zs)); print(p)

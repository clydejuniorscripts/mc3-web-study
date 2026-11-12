#!/usr/bin/env python3
"""tools_xbe.py dw <hexva> [n]   : n dwords of the XBE image at va (function names where they are code)
   tools_xbe.py f  <hexva> [n]   : n floats
   tools_xbe.py s  <hexva>       : C string"""
import struct, sys, os
X = open(os.path.expanduser("~/mc3-web/game/default.xbe"), "rb").read()
base, = struct.unpack_from("<I", X, 0x104)
nsec, sech = struct.unpack_from("<II", X, 0x11C)
S = []
for i in range(nsec):
    fl, va, vs, ra, rs = struct.unpack_from("<IIIII", X, sech - base + i * 0x38)
    S.append((va, vs, ra, rs))
def rd(va, n):
    for v, vs, ra, rs in S:
        if v <= va < v + vs:
            o = va - v
            return (X[ra + o: ra + min(o + n, rs)] + b"\0" * n)[:n]
    return None
c = sys.argv[1]; va = int(sys.argv[2], 16); n = int(sys.argv[3]) if len(sys.argv) > 3 else 16
if c == "dw":
    for i in range(n):
        b = rd(va + 4 * i, 4)
        if b is None: print("%08X unmapped" % (va + 4 * i)); break
        d, = struct.unpack("<I", b)
        print("%08X +%03X  %08X" % (va + 4 * i, 4 * i, d))
elif c == "f":
    for i in range(n):
        b = rd(va + 4 * i, 4); print("%08X +%03X  %g" % (va + 4 * i, 4 * i, struct.unpack("<f", b)[0]))
elif c == "s":
    b = rd(va, 200); print(repr(b.split(b"\0")[0]))

#!/usr/bin/env python3
"""tools_icons.py -- the game's HUD map icons (texture_x/icon_*.tex from assets_x.dat) as PNGs.

  python3 tools_icons.py <dir with texture_x/icon_*.tex> <out dir>

.tex: u16 width, u16 height, u16 format (0x1A = DXT5), u16 1, u16 mip count, u32 0, then the
DXT5 blocks (16 bytes per 4x4 block). Decoded through a DDS header with Pillow, as
tools_decode_hudmap.py does. Extract the .tex files first:
  python3 tools_dave.py extract assets_x.dat '^texture_x/icon_' /tmp/ic
"""
import glob, io, os, struct, sys
from PIL import Image


def dds(buf, w, h, fourcc=b"DXT5"):   # as tools_decode_hudmap.py's (which runs on import)
    return (b"DDS " + struct.pack("<I", 124) +
            struct.pack("<IIIII", 0x1|0x2|0x4|0x1000|0x80000, h, w, len(buf), 0) +
            struct.pack("<I", 0) + bytes(44) +
            struct.pack("<II", 32, 0x4) + fourcc + struct.pack("<IIIII", 0,0,0,0,0) +
            struct.pack("<IIIII", 0x1000,0,0,0,0) + buf)

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
for p in sorted(glob.glob(os.path.join(src, 'texture_x', 'icon_*.tex'))):
    b = open(p, 'rb').read()
    w, h, fmt, _one, mips = struct.unpack_from('<5H', b, 0)
    if fmt != 0x1A:
        print('skip', p, hex(fmt)); continue
    n = max(1, w // 4) * max(1, h // 4) * 16
    im = Image.open(io.BytesIO(dds(b[14:14 + n], w, h, b"DXT5"))).convert('RGBA')
    name = os.path.basename(p)[:-4] + '.png'
    im.save(os.path.join(out, name))
    print(name, w, h)

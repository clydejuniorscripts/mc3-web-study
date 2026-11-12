import struct, io, sys
from PIL import Image

SRC = "/root/mc3-web/game/resources/city/hudmap.xbpf"
# resolve home: this runs as the WSL user; try both
import os
for p in (SRC, os.path.expanduser("~/mc3-web/game/resources/city/hudmap.xbpf")):
    if os.path.exists(p): SRC = p; break
OUT = sys.argv[1]

d = open(SRC, "rb").read()
data = d[0x10800:]

def dds(buf, w, h, fourcc=b"DXT1"):
    return (b"DDS " + struct.pack("<I", 124) +
            struct.pack("<IIIII", 0x1|0x2|0x4|0x1000|0x80000, h, w, len(buf), 0) +
            struct.pack("<I", 0) + b"\x00"*44 +
            struct.pack("<II", 32, 0x4) + fourcc + struct.pack("<IIIII", 0,0,0,0,0) +
            struct.pack("<IIIII", 0x1000,0,0,0,0) + buf)

def decode(buf, w, h, fourcc=b"DXT1"):
    return Image.open(io.BytesIO(dds(buf, w, h, fourcc))).convert("RGB")

# Full decode: DXT5, 256-wide; split into 256x256 tiles; use alpha to drop the hatch.
W = 256
h = (len(data)//W); h -= h % 4
rgba = Image.open(io.BytesIO(dds(data[:W*h], W, h, b"DXT5")))   # RGBA
ntiles = h // 256
print("tiles:", ntiles, "alpha range:", rgba.split()[3].getextrema())
tiles = []
for i in range(ntiles):
    t = rgba.crop((0, i*256, 256, i*256+256))
    bg = Image.new("RGB", (256,256), (20,24,30))
    bg.paste(t, (0,0), t)              # composite using alpha -> hatch (alpha=0) becomes bg
    tiles.append(bg)
    bg.save(f"{OUT}/tile_{i:02d}.png")
# contact sheet
import math
cols = 8; rows = math.ceil(ntiles/cols); TH = 128
sheet = Image.new("RGB", (cols*TH, rows*TH), (10,10,10))
from PIL import ImageDraw
dr = ImageDraw.Draw(sheet)
for i,t in enumerate(tiles):
    th = t.resize((TH,TH))
    x,y = (i%cols)*TH, (i//cols)*TH
    sheet.paste(th,(x,y)); dr.text((x+2,y+2), str(i), fill=(255,230,120))
sheet.save(f"{OUT}/contact.png")
print("wrote", ntiles, "tiles + contact.png")

def morton_deswizzle(buf, bw, bh):   # blocks across/down (powers of two)
    out = bytearray(bw*bh*8)
    for m in range(bw*bh):
        x = y = 0
        for b in range(12):
            x |= ((m >> (2*b)) & 1) << b
            y |= ((m >> (2*b+1)) & 1) << b
        src = m*8; dst = (y*bw + x)*8
        if dst+8 <= len(out) and src+8 <= len(buf):
            out[dst:dst+8] = buf[src:src+8]
    return bytes(out)

results = []
for TILE in (128, 256, 512):
    n = TILE*TILE//2
    buf = data[:n]
    if len(buf) < n: continue
    bw = TILE//4
    # linear
    decode(buf, TILE, TILE).save(f"{OUT}/dec_{TILE}_lin.png")
    # morton de-swizzle
    decode(morton_deswizzle(buf, bw, bw), TILE, TILE).save(f"{OUT}/dec_{TILE}_mort.png")
    results.append(TILE)
print("decoded tiles:", results)

#!/usr/bin/env python3
"""Make stand-ins for the disc's Bink movies: the same file cut down to its first frames.

    tools_novideo.py [frames=2]      game/**/*.bik  ->  game-novideo/<same path>

Movies streamed badly for players (2026-11-10), so the web server hands out these instead
(web/serve.py, MC3_NO_VIDEO): the game opens a movie, gets a valid two-frame film and is
through it at once. The real files on the disc are not touched.

Bink 1 header (little-endian dwords): 0 'BIK'+revision, 4 file size - 8, 8 frames,
12 largest frame, 16 frames again, 20 width, 24 height, 28/32 fps, 36 video flags,
40 audio tracks, then per track 4 (max decoded size) + 4 (rate, flags) + 4 (id) bytes,
then the frame offset table (bit 0 = key frame), frames+1 entries, then the frames.
"""
import os, struct, sys, pathlib

KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 2
repo = pathlib.Path.home() / "mc3-web"
src_root, dst_root = repo / "game", repo / "game-novideo"

def cut(src, dst):
    with open(src, "rb") as f:
        head = f.read(44)
        if head[:3] != b"BIK":
            return "not Bink 1 (%r)" % head[:4]
        frames = struct.unpack_from("<I", head, 8)[0]
        tracks = struct.unpack_from("<I", head, 40)[0]
        table_at = 44 + tracks * 12
        f.seek(0)
        hdr = bytearray(f.read(table_at))
        first = struct.unpack("<I", f.read(4))[0]
        entries = ((first & ~1) - table_at) // 4          # frames + 1 on every file seen
        if entries not in (frames, frames + 1):
            return "unexpected offset table (%d entries for %d frames)" % (entries, frames)
        f.seek(table_at)
        offs = list(struct.unpack("<%dI" % entries, f.read(4 * entries)))
        size = os.path.getsize(src)
        ends = [o & ~1 for o in offs[1:]] + ([size] if entries == frames else [])
        n = min(KEEP, frames)
        start = offs[0] & ~1
        end = ends[n - 1]
        f.seek(start)
        body = f.read(end - start)
    new_entries = n + (1 if entries == frames + 1 else 0)
    shift = start - (table_at + 4 * new_entries)          # the table got shorter
    table = [((offs[i] & ~1) - shift) | (offs[i] & 1) for i in range(n)]
    if entries == frames + 1:
        table.append(end - shift)
    sizes = [ends[i] - (offs[i] & ~1) for i in range(n)]
    total = table_at + 4 * new_entries + len(body)
    struct.pack_into("<I", hdr, 4, total - 8)
    struct.pack_into("<I", hdr, 8, n)
    struct.pack_into("<I", hdr, 12, max(sizes))
    if struct.unpack_from("<I", hdr, 16)[0] == frames:
        struct.pack_into("<I", hdr, 16, n)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as o:
        o.write(hdr); o.write(struct.pack("<%dI" % new_entries, *table)); o.write(body)
    return "%d of %d frames, %.1f MB -> %d KB" % (n, frames, size / 1e6, total // 1024)

done = bad = 0
for p in sorted(src_root.rglob("*")):
    if p.is_file() and p.suffix.lower() == ".bik":
        rel = p.relative_to(src_root)
        r = cut(p, dst_root / rel)
        ok = r[0].isdigit()
        done += ok; bad += not ok
        print(("  " if ok else "!! ") + str(rel) + ": " + r)
print("%d movies cut, %d left alone; stand-ins in %s" % (done, bad, dst_root))

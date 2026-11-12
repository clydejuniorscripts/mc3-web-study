#!/usr/bin/env python3
"""Emscripten's WasmFS fetch backend: send every file through the ranged
path. Files of up to two chunks took a "download it whole" shortcut whose
reads came back as zeros past the first chunk (rockstar.bik, 1.3 MB, read as
zeros from 1 MB on: the Bink decoder then failed at frame 75). The ranged
path is the one verified byte for byte on the multi-chunk files."""
import pathlib
p = pathlib.Path.home() / "emsdk/upstream/emscripten/src/lib/libwasmfs_fetch.js"
s = p.read_text()
old = "            (parseInt(fileInfo.headers.get('Content-Length'), 10) > chunkSize*2)) {"
new = "            true /* mc3-web: always ranged (the whole-file shortcut read zeros past chunk 0) */) {"
if new in s:
    print("already")
else:
    assert old in s
    p.write_text(s.replace(old, new, 1))
    print("ok", p)

#!/usr/bin/env python3
"""Emscripten's glMapBufferRange also insists on an INVALIDATE flag (it maps a
fresh heap block and uploads it whole at unmap). Every mapped range is
written in full, so INVALIDATE_RANGE is correct here."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
a = "#define NV2A_MAP_UNSYNC 0      /* WebGL 2: Emscripten's map emulation refuses it */"
b = ("#define NV2A_MAP_UNSYNC GL_MAP_INVALIDATE_RANGE_BIT   /* WebGL 2: Emscripten's map emulation\n"
     "                          refuses UNSYNCHRONIZED and requires an INVALIDATE flag */")
if b in s:
    print("already")
else:
    assert a in s
    p.write_text(s.replace(a, b, 1)); print("ok")

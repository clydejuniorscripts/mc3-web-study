#!/usr/bin/env python3
"""WebGL 2: map buffers without GL_MAP_UNSYNCHRONIZED_BIT. Emscripten emulates
glMapBufferRange (a heap block, uploaded with bufferSubData at unmap) but
refuses the unsynchronised flag and returns NULL. Without it, the renderer's
mapped streaming and its draw merging work as on the desktop."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
DEF = """
#if defined(__EMSCRIPTEN__)
#define NV2A_MAP_UNSYNC 0      /* WebGL 2: Emscripten's map emulation refuses it */
#else
#define NV2A_MAP_UNSYNC GL_MAP_UNSYNCHRONIZED_BIT
#endif
"""
if "NV2A_MAP_UNSYNC" in s:
    print("already")
else:
    anchor = '#include "gl_merge.h"'
    i = s.index(anchor)
    j = s.index("\n", i) + 1
    s = s[:j] + DEF + s[j:]
    n = s.count("GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT")
    s = s.replace("GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT", "GL_MAP_WRITE_BIT | NV2A_MAP_UNSYNC")
    p.write_text(s)
    print("ok, replaced", n)

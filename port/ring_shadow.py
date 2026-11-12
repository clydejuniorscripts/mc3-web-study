#!/usr/bin/env python3
"""Streaming rings on the web: write into a CPU shadow of the ring and upload
the written range with glBufferSubData, instead of Emscripten's
glMapBufferRange emulation (a heap block allocated, copied and freed in
JavaScript for every map, i.e. every draw)."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "ring_shadow(" in s:
    print("already"); sys.exit(0)

def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:60], s.count(a))
    s = s.replace(a, b, 1)

rep("    int seg;                    /* the quarter being filled */\n} GlRing;",
    "    int seg;                    /* the quarter being filled */\n"
    "    uint8_t *shadow;            /* web: CPU copy written in place of a map */\n"
    "    GLsizeiptr shadow_cap;\n} GlRing;")
rep("static int ring_persist(GlRing *g);\n",
    "static int ring_persist(GlRing *g);\n"
    "#if defined(__EMSCRIPTEN__)\n"
    "static void *ring_shadow(GlRing *g, GLintptr at)\n{\n"
    "    if (g->shadow_cap < g->cap) {\n"
    "        free(g->shadow);\n"
    "        g->shadow = (uint8_t *)malloc((size_t)g->cap);\n"
    "        g->shadow_cap = g->shadow ? g->cap : 0;\n"
    "    }\n"
    "    return g->shadow ? g->shadow + at : NULL;\n}\n#endif\n")
rep("    *ptr = glMapBufferRange(g->target, at, size,\n"
    "                            GL_MAP_WRITE_BIT | NV2A_MAP_UNSYNC\n"
    "                            );",
    "#if defined(__EMSCRIPTEN__)\n    *ptr = ring_shadow(g, at);\n#else\n"
    "    *ptr = glMapBufferRange(g->target, at, size,\n"
    "                            GL_MAP_WRITE_BIT | NV2A_MAP_UNSYNC\n"
    "                            );\n#endif")
rep("    *ptr = glMapBufferRange(g->target, at, size, GL_MAP_WRITE_BIT | NV2A_MAP_UNSYNC);\n    return 1;",
    "#if defined(__EMSCRIPTEN__)\n    *ptr = ring_shadow(g, at);\n#else\n"
    "    *ptr = glMapBufferRange(g->target, at, size, GL_MAP_WRITE_BIT | NV2A_MAP_UNSYNC);\n#endif\n    return 1;")
rep("    if (ptr)\n        glUnmapBuffer(g->target);\n",
    "    if (ptr)\n#if defined(__EMSCRIPTEN__)\n"
    "        glBufferSubData(g->target, at, size, ptr);     /* the shadow's range */\n#else\n"
    "        glUnmapBuffer(g->target);\n#endif\n")
p.write_text(s)
print("ok")

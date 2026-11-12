#!/usr/bin/env python3
"""Module._web_gl_ringbatch(0|1): batched ring uploads off/on while running
(A/B). Off: every ring_done uploads its range at once, as before."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "web_gl_ringbatch" in s:
    print("already"); sys.exit(0)
a = "static void ring_flush_all(void)\n{"
assert s.count(a) == 1
s = s.replace(a, '''static int s_ring_batch = 1;
#if defined(__EMSCRIPTEN__)
EMSCRIPTEN_KEEPALIVE void web_gl_ringbatch(int on)
{
    s_ring_batch = on != 0;
    fprintf(stderr, "  [GL] vertex uploads %s\\n", on ? "batched per call" : "per draw");
}
#endif
''' + a, 1)
a = "            g->plo = at;\n            g->phi = at + size;\n        }\n        return;\n"
assert s.count(a) == 1
s = s.replace(a, "            g->plo = at;\n            g->phi = at + size;\n        }\n"
                 "        if (!s_ring_batch)\n            ring_flush(g);\n        return;\n", 1)
p.write_text(s)
c = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
t = c.read_text()
if "_web_gl_ringbatch" not in t:
    c.write_text(t.replace("_web_gl_texmerge", "_web_gl_texmerge,_web_gl_ringbatch", 1))
print("ok")

#!/usr/bin/env python3
"""Module._web_gl_texmerge(0|1): texture merging off/on while running, for
A/B measurements on the same stretch of road. Programs keep their slot
shaders; off, draws simply stop folding by texture."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "web_gl_texmerge" not in s:
    a = "/* Held-back texture binds (texmerge): onto units 0-3 now. */"
    assert s.count(a) == 1
    s = s.replace(a, '''#if defined(__EMSCRIPTEN__)
EMSCRIPTEN_KEEPALIVE void web_gl_texmerge(int on)
{
    if (nv2a_gl_tslots)
        s_tm_on = on ? 1 : 0;
    fprintf(stderr, "  [GL] texture merging %s\\n", s_tm_on > 0 ? "on" : "off");
}
#endif

''' + a, 1)
    p.write_text(s)
c = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
t = c.read_text()
if "_web_gl_texmerge" not in t:
    assert "_web_gl_tick" in t
    c.write_text(t.replace("_web_gl_tick", "_web_gl_tick,_web_gl_texmerge", 1))
print("ok")

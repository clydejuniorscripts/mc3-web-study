#!/usr/bin/env python3
"""GL thread pacing on the web.

1. The GL queue was drained from requestAnimationFrame, one flip per tick.
   A tick that takes 34 ms misses the next 60 Hz refresh and the frame lands
   on the one after: 34 ms of work became 50 ms frames (20 fps). Drained from
   a 1 ms timer instead (WEB_GL_LOOP=timer; measured worse: 8.8 vs 25 fps on the menu, so off by default), a frame is
   shown when it is done; the OffscreenCanvas presents when the tick returns.
   A side effect: rendering also continues while the page is hidden.
2. Spinning before sleeping on locks (spin_fix.py) made races slower; its
   default is now 0 (RECOMP_SPIN_US enables it)."""
import pathlib
root = pathlib.Path.home() / "mc3-web/xboxrecomp/src"
p = root / "nv2a_gl/nv2a_gl.c"
s = p.read_text()
a = "    emscripten_set_main_loop(q_web_tick, 0, 1);   /* does not return */"
b = ("    {\n"
     "        const char *e = getenv(\"WEB_GL_LOOP\");\n"
     "        int raf = !(e && !strcmp(e, \"timer\"));\n"
     "        fprintf(stderr, \"  [GL] queue drained %s (WEB_GL_LOOP)\\n\",\n"
     "                raf ? \"at each animation frame\" : \"from a 1 ms timer: frames shown when done\");\n"
     "        emscripten_set_main_loop(q_web_tick, raf ? 0 : 1000, 1);   /* does not return */\n"
     "    }")
if b in s:
    print("already loop")
else:
    assert a in s
    p.write_text(s.replace(a, b, 1)); print("ok loop")
for f in ["kernel/kernel_bridge.c", "kernel/kernel_hal.c"]:
    q = root / f
    t = q.read_text()
    a2 = "ms = (e ? atof(e) : 50.0) / 1000.0;"
    if a2 in t:
        q.write_text(t.replace(a2, "ms = (e ? atof(e) : 0.0) / 1000.0;   /* off unless asked */", 1)); print("ok spin off", f)
    else:
        print("already", f)

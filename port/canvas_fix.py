#!/usr/bin/env python3
"""Hand the page's canvas down: main thread -> title's thread -> GL thread.
Emscripten only transfers a canvas from the thread that owns it; the main
thread owns the DOM one, a pthread owns it once handed over (by bare id)."""
import pathlib
root = pathlib.Path.home() / "mc3-web"

def edit(rel, a, b):
    p = root / rel
    s = p.read_text()
    if b in s:
        print("already", rel); return
    assert a in s, (rel, a[:70])
    p.write_text(s.replace(a, b, 1))
    print("ok", rel)

edit("xboxrecomp/src/platform/host_main.c",
     "    pthread_attr_setstacksize(&attr, (size_t)64 << 20);\n    if (pthread_create(&th, &attr, web_guest, &w) != 0) {",
     "    pthread_attr_setstacksize(&attr, (size_t)64 << 20);\n"
     "    {   /* the page's canvas goes with the title; its GL thread takes it on */\n"
     "        extern int emscripten_pthread_attr_settransferredcanvases(pthread_attr_t *, const char *);\n"
     "        emscripten_pthread_attr_settransferredcanvases(&attr, \"#canvas\");\n"
     "    }\n"
     "    if (pthread_create(&th, &attr, web_guest, &w) != 0) {")
edit("xboxrecomp/src/nv2a_gl/nv2a_gl.c",
     "        emscripten_pthread_attr_settransferredcanvases(&at, \"#canvas\");",
     "        emscripten_pthread_attr_settransferredcanvases(&at, \"canvas\");   /* owned by this thread */")

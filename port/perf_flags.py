#!/usr/bin/env python3
"""Release link flags for speed: no Emscripten assertions (checks on every
JS-glue call, every GL call included) and no GL error tracking. WEB_DEBUG=1
in the build environment keeps assertions for diagnosis."""
import pathlib
p = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
s = p.read_text()
a = "--profiling-funcs -sASSERTIONS=1"
b = "--profiling-funcs $<IF:$<BOOL:$ENV{WEB_DEBUG}>,-sASSERTIONS=1,-sASSERTIONS=0> -sGL_TRACK_ERRORS=0"
if b in s:
    print("already")
else:
    assert a in s, "anchor"
    p.write_text(s.replace(a, b, 1)); print("ok")

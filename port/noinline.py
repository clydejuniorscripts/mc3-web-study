#!/usr/bin/env python3
"""Debug aid: build the GL renderer without inlining (WEB_GL_DEBUG=1 in the
environment of the build adds it; off by default) so traps name the function."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/CMakeLists.txt"
s = p.read_text()
a = "    target_compile_options(xbox_nv2a_gl PRIVATE -Wall -Wextra -Wno-unused-parameter -O2)"
b = (a + "\n    if(EMSCRIPTEN AND \"$ENV{WEB_GL_DEBUG}\" STREQUAL \"1\")\n"
     "        target_compile_options(xbox_nv2a_gl PRIVATE -fno-inline -O1)\n    endif()")
if b in s:
    print("already")
else:
    assert a in s
    p.write_text(s.replace(a, b, 1)); print("ok")

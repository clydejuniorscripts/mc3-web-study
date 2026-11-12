#!/usr/bin/env python3
"""Link web/pre.js (worker error stacks) into the web build."""
import pathlib
p = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
s = p.read_text()
a = "-sGLOBAL_BASE=68157440"
b = "--pre-js=${CMAKE_CURRENT_SOURCE_DIR}/web/pre.js -sGLOBAL_BASE=68157440"
if b in s:
    print("already")
else:
    assert a in s
    p.write_text(s.replace(a, b, 1))
    print("ok")

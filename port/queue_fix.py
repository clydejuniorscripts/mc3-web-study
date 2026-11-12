#!/usr/bin/env python3
"""GL queue byte counters: 64-bit. As size_t they wrap at 4 GB on wasm32, and
since the 48 MB ring does not divide 2^32 the read and write positions then
disagree: the GL thread read garbage (out-of-bounds traps) or waited forever
(a frozen race). On 64-bit hosts nothing changes."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
a = "static size_t s_q_head, s_q_tail;               /* bytes written / read, ever */"
b = ("static uint64_t s_q_head, s_q_tail;             /* bytes written / read, ever (64-bit:\n"
     "                                                   a 32-bit size_t wraps within minutes) */")
if b in s:
    print("already")
else:
    assert a in s
    p.write_text(s.replace(a, b, 1)); print("ok")

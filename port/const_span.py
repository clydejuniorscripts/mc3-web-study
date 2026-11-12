#!/usr/bin/env python3
"""Vertex constants on the web: one glUniform4fv for the span from the first
to the last changed row, instead of one call per run of changed rows. A
WebGL call costs microseconds (JS glue, validation, the command buffer);
bytes are cheap. Native hosts keep the per-run upload."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "web: one call for the changed span" in s:
    print("already"); sys.exit(0)
a = """            int r = 0;
            while (r < p->n_c) {"""
b = """            int r = 0;
#if defined(__EMSCRIPTEN__)
            {   /* web: one call for the changed span (calls cost, bytes do not) */
                int lo = 0, hi = p->n_c - 1;
                while (lo < p->n_c && !memcmp(p->vpc[lo], b->vp_consts[lo], 16)) lo++;
                if (lo < p->n_c) {
                    while (hi > lo && !memcmp(p->vpc[hi], b->vp_consts[hi], 16)) hi--;
                    memcpy(p->vpc[lo], b->vp_consts[lo], (size_t)(hi - lo + 1) * 16);
                    s_pf_crows += (uint32_t)(hi - lo + 1);
                    glUniform4fv(p->u_c + lo, hi - lo + 1, &b->vp_consts[lo][0]);
                }
                r = p->n_c;                  /* the per-run loop below has nothing left */
            }
#endif
            while (r < p->n_c) {"""
assert s.count(a) == 1, s.count(a)
p.write_text(s.replace(a, b, 1))
print("ok")

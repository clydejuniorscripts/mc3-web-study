#!/usr/bin/env python3
"""Web: one glBufferSubData per GL draw call instead of one per game draw.

Since ring_shadow.py the streaming rings (vertices, indices) are written in
a CPU shadow and each ring_done copied its range up with glBufferSubData.
A merged call of 20 folded draws therefore made ~40 uploads. Now ring_done
only widens a pending range while allocations follow each other (the
64-byte alignment gaps go up too, harmlessly), and the range goes up:
- before every draw from the rings (SGN_DRAW, both draw paths),
- before the ring is orphaned at its wrap (the data belongs to the old
  storage),
- when an allocation does not follow the pending range."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "ring_flush_all" in s:
    print("already"); sys.exit(0)

def rep(a, b, count=1):
    global s
    assert s.count(a) == count, (a[:80], s.count(a))
    s = s.replace(a, b)

rep("    uint8_t *shadow;            /* web: CPU copy written in place of a map */\n    GLsizeiptr shadow_cap;\n} GlRing;",
    "    uint8_t *shadow;            /* web: CPU copy written in place of a map */\n    GLsizeiptr shadow_cap;\n"
    "    GLintptr plo, phi;          /* web: shadow bytes not yet uploaded (ring_flush) */\n} GlRing;")
rep("static GLintptr ring_alloc(GlRing *g, GLsizeiptr size, void **ptr)\n{",
    r'''/* Web: the shadow's pending range up to the GL buffer. */
static void ring_flush(GlRing *g)
{
#if defined(__EMSCRIPTEN__)
    if (g->phi > g->plo && g->shadow) {
        glBindBuffer(g->target, g->buf);
        glBufferSubData(g->target, g->plo, g->phi - g->plo, g->shadow + g->plo);
    }
    g->plo = g->phi = 0;
#else
    (void)g;
#endif
}
static void ring_flush_all(void)
{
#if defined(__EMSCRIPTEN__)
    ring_flush(&s_vring);
    ring_flush(&s_iring);
    ring_flush(&s_uring);
#endif
}

static GLintptr ring_alloc(GlRing *g, GLsizeiptr size, void **ptr)
{''')
rep("    at = (g->off + 63) & ~(GLintptr)63;\n    if (at + size > g->cap) {\n        glBufferData(g->target, g->cap, NULL, GL_STREAM_DRAW);",
    "    at = (g->off + 63) & ~(GLintptr)63;\n    if (at + size > g->cap) {\n"
    "        ring_flush(g);                      /* into the storage it was written for */\n"
    "        glBufferData(g->target, g->cap, NULL, GL_STREAM_DRAW);")
rep('''    if (ptr)
#if defined(__EMSCRIPTEN__)
        glBufferSubData(g->target, at, size, ptr);     /* the shadow's range */
#else''', '''#if defined(__EMSCRIPTEN__)
    if (ptr) {                              /* the shadow's range: up before the draw */
        if (g->phi > g->plo && at >= g->phi && at <= g->phi + 64) {
            g->phi = at + size;
        } else {
            ring_flush(g);
            g->plo = at;
            g->phi = at + size;
        }
        return;
    }
#endif
    if (ptr)
#if defined(__EMSCRIPTEN__)
        glBufferSubData(g->target, at, size, ptr);     /* (not reached) */
#else''')
rep("#define SGN_DRAW(prog, CALL) do {                                             \\\n",
    "#define SGN_DRAW(prog, CALL) do {                                             \\\n"
    "    ring_flush_all();                     /* web: pending vertex/index data */ \\\n")
p.write_text(s)
print("ok")

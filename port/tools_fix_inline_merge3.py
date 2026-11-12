"""Narrow the inline-draw merge exclusion (2026-11-11): only single-triangle inline draws (3
vertices: MC3's minimap arrows, an outline then a fill) stay unmerged. Excluding every inline
draw made the Flash menus and loading screens (also inline draws) 2-3x slower: boot to the
main menu 66 s instead of 32 s, frames up to 500 ms. RECOMP_GL_MERGE_INLINE=1 merges all
(the old behaviour), =0 merges none. Idempotent."""
import io, os
p = os.path.expanduser('~/mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c')
t = io.open(p, encoding='utf-8', newline='').read()
if 'vertex_count <= 3' in t:
    print('already'); raise SystemExit
a = ("            if (s_merge_inline < 0) { const char *e = getenv(\"RECOMP_GL_MERGE_INLINE\"); s_merge_inline = e && *e == '1'; }\n"
     "            s_inline_nomerge = b->from_inline && !s_merge_inline;")
b = ("            if (s_merge_inline < 0) { const char *e = getenv(\"RECOMP_GL_MERGE_INLINE\"); s_merge_inline = !e ? 2 : *e == '1' ? 1 : 0; }\n"
     "            /* 2 (default): only single-triangle inline draws stay apart -- the minimap\n"
     "             * arrows; the menus' and loading screens' inline quads still merge */\n"
     "            s_inline_nomerge = b->from_inline && (s_merge_inline == 0 || (s_merge_inline == 2 && b->vertex_count <= 3));")
assert t.count(a) == 1, t.count(a); t = t.replace(a, b)
io.open(p, 'w', encoding='utf-8', newline='').write(t); print('edited')

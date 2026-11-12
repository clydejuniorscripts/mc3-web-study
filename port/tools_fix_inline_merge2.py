"""Make the inline-draw merge exclusion switchable: RECOMP_GL_MERGE_INLINE=1 merges inline-array
draws again (the old behaviour), for A/B timing of the front end. Idempotent."""
import io, os
p = os.path.expanduser('~/mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c')
t = io.open(p, encoding='utf-8', newline='').read()
if 's_merge_inline' in t:
    print('already'); raise SystemExit
a = "        ml = s_merge_on && mmode == GL_TRIANGLES && !s_watch_hit && s_finish <= 0\n             && !b->from_inline && merge_layout(b, &L);"
b = ("        {   /* RECOMP_GL_MERGE_INLINE=1: merge inline-array draws too (as before 2026-11-11) */\n"
     "            static int s_merge_inline = -1;\n"
     "            if (s_merge_inline < 0) { const char *e = getenv(\"RECOMP_GL_MERGE_INLINE\"); s_merge_inline = e && *e == '1'; }\n"
     "            s_inline_nomerge = b->from_inline && !s_merge_inline;\n"
     "        }\n"
     "        ml = s_merge_on && mmode == GL_TRIANGLES && !s_watch_hit && s_finish <= 0\n             && !s_inline_nomerge && merge_layout(b, &L);")
assert t.count(a) == 1; t = t.replace(a, b)
a2 = "             && !b->from_inline && s_finish <= 0"
assert t.count(a2) == 1; t = t.replace(a2, "             && !s_inline_nomerge && s_finish <= 0")
a3 = "static int s_mg_active;"
if a3 not in t:
    # declare near the merge state instead
    a3 = "static int s_merge_on = -1;"
assert t.count(a3) >= 1
t = t.replace(a3, a3 + "\nstatic int s_inline_nomerge;   /* this draw came inline and is not merged (RECOMP_GL_MERGE_INLINE) */", 1)
io.open(p, 'w', encoding='utf-8', newline='').write(t); print('edited')

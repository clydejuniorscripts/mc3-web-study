"""Renderer fix (2026-11-11): draws made of INLINE_ARRAY vertices are never merged.
Consecutive inline draws that the GL back end folded together came out in the wrong colour
(MC3's minimap arrows: black outline, coloured fill, drawn back to back -> both black;
RECOMP_GL_MERGE=0 made them right). The batch now says it came from the inline array.
Idempotent: run again and it changes nothing."""
import io, os, sys
R = os.path.expanduser('~/mc3-web/xboxrecomp/src/')
def edit(path, a, b):
    p = R + path; t = io.open(p, encoding='utf-8', newline='').read()
    if b in t:
        print('already', path); return
    assert t.count(a) == 1, (path, a[:60], t.count(a))
    io.open(p, 'w', encoding='utf-8', newline='').write(t.replace(a, b)); print('edited', path)

edit('kernel/nv2a_backend.h',
     "    uint32_t        vtx_epoch;\n} Nv2aRawBatch;",
     "    uint32_t        vtx_epoch;\n"
     "    /* The vertices came in the pushbuffer (INLINE_ARRAY: D3D's DrawPrimitiveUP),\n"
     "     * not from vertex memory: direct[] points into the executor's inline buffer,\n"
     "     * which the next inline batch overwrites. */\n"
     "    uint8_t         from_inline;\n"
     "} Nv2aRawBatch;")
edit('kernel/nv2a_pb_exec.c',
     "    uint16_t mask = 0;\n    uint32_t a;\n\n    for (a = 0; a < NV2A_RAW_ATTRS; a++) {\n        const VertexAttr *va = &s_gpu.attr[a];",
     "    uint16_t mask = 0;\n    uint32_t a;\n\n    rb->from_inline = (uint8_t)(s_gpu.inline_active != 0);\n"
     "    for (a = 0; a < NV2A_RAW_ATTRS; a++) {\n        const VertexAttr *va = &s_gpu.attr[a];")
edit('nv2a_gl/nv2a_gl.c',
     "        ml = s_merge_on && mmode == GL_TRIANGLES && !s_watch_hit && s_finish <= 0\n             && merge_layout(b, &L);",
     "        /* Inline-array draws (small: HUD icons, the menu sign) are not merged: folded\n"
     "         * together, back-to-back ones came out in one colour -- MC3's minimap arrows,\n"
     "         * a black outline then a coloured fill, all drawn black (2026-11-11). */\n"
     "        ml = s_merge_on && mmode == GL_TRIANGLES && !s_watch_hit && s_finish <= 0\n             && !b->from_inline && merge_layout(b, &L);")
edit('nv2a_gl/nv2a_gl.c',
     "        sl = !ml && s_merge_on && s_merge_on != 2 && mmode == GL_TRIANGLES && !s_watch_hit\n             && s_finish <= 0",
     "        sl = !ml && s_merge_on && s_merge_on != 2 && mmode == GL_TRIANGLES && !s_watch_hit\n             && !b->from_inline && s_finish <= 0")

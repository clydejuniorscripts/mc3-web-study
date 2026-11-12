#!/usr/bin/env python3
"""Texture slots carry the combiner constants too (after texmerge.py).

In MC3 races ~60 draws per frame differed from the held one in textures
and the pixel combiner constants c0/c1 (D3D's per-stage TFACTOR-like
colours). Per-draw copies like the matrices would need 16 x 16 fragment
vectors; per slot it is 4 x 16. So a slot is now (textures, c0, c1):
- gl_psh.c reads u_c0[NV_C+i] / u_c1[NV_C+i], NV_C = vDslot * 8, from
  arrays of 32 (4 slots x 8 stages).
- A draw whose uniforms differ from the held one's only in c0/c1 (and the
  matrices, for per-draw-matrix programs) folds with a slot holding its
  constants; the flush uploads every slot's rows, then puts the latest
  draw's back in slot 0.
- Rows a program's combiners never read (beyond its stage count, or all
  when per-stage constants are off) no longer count as a change at all."""
import pathlib, sys

src = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl"
P = {n: src / n for n in ["nv2a_gl.c", "gl_psh.c", "gl_psh.h"]}
T = {n: p.read_text() for n, p in P.items()}
if "NV_C" in T["gl_psh.c"]:
    print("already"); sys.exit(0)
assert "RECOMP_GL_TEXMERGE" in T["nv2a_gl.c"], "texmerge.py first"

def rep(f, a, b, count=1):
    s = T[f]
    assert s.count(a) == count, (f, a[:80], s.count(a))
    T[f] = s.replace(a, b)

# ── gl_psh.h / gl_psh.c ─────────────────────────────────────────────────
rep("gl_psh.h", "extern int nv2a_shader_vk;\n",
    "extern int nv2a_shader_vk;\nextern int nv2a_gl_tslots;   /* texture slots (nv2a_gl.c texmerge) */\n")
rep("gl_psh.c", '        snprintf(buf, n, "u_c0[%d]", (k->control & (1u << 12)) ? stage : 0);',
    '        snprintf(buf, n, nv2a_gl_tslots && !nv2a_shader_vk ? "u_c0[NV_C+%d]" : "u_c0[%d]",\n'
    '                 (k->control & (1u << 12)) ? stage : 0);')
rep("gl_psh.c", '        snprintf(buf, n, "u_c1[%d]", (k->control & (1u << 16)) ? stage : 0);',
    '        snprintf(buf, n, nv2a_gl_tslots && !nv2a_shader_vk ? "u_c1[NV_C+%d]" : "u_c1[%d]",\n'
    '                 (k->control & (1u << 16)) ? stage : 0);')
rep("gl_psh.c", '    "flat in int vDslot;\\n" \\\n',
    '    "flat in int vDslot;\\n" \\\n    "#define NV_C (vDslot * 8)\\n" \\\n')
rep("gl_psh.c", '        "uniform vec4 u_c0[8]; uniform vec4 u_c1[8];\\n"\n',
    '        "%s"\n')
rep("gl_psh.c", '        "void main() {\\n", nv2a_gl_tslots ? TSLOT_DECL : "");',
    '        "void main() {\\n", nv2a_gl_tslots ? TSLOT_DECL : "",\n'
    '        nv2a_gl_tslots ? "uniform vec4 u_c0[32]; uniform vec4 u_c1[32];\\n"\n'
    '                       : "uniform vec4 u_c0[8]; uniform vec4 u_c1[8];\\n");')

# ── nv2a_gl.c ───────────────────────────────────────────────────────────
f = "nv2a_gl.c"
rep(f, "static int s_tex_diff;          /* ... and they differ from the held call's latest set */\n",
    "static int s_tex_diff;          /* ... and they differ from the held call's latest set */\n"
    "static int s_cdiff;             /* this draw's combiner constants differ from it (deferred) */\n")
rep(f, "    s_want_mask = 0;\n    s_tex_diff = 0;\n",
    "    s_want_mask = 0;\n    s_tex_diff = 0;\n    s_cdiff = 0;\n")
# A program takes slots only if its constant arrays hold every slot's rows.
rep(f, "    if (s_tm_on > 0) {                       /* slot k's stage i: unit 4k+i */\n",
    "    if (p->tslot && !((p->u_c0 < 0 || arr_active(p->prog, \"u_c0\", 8 * TM_SLOTS) == 8 * TM_SLOTS)\n"
    "                      && (p->u_c1 < 0 || arr_active(p->prog, \"u_c1\", 8 * TM_SLOTS) == 8 * TM_SLOTS)))\n"
    "        p->tslot = 0;\n"
    "    if (s_tm_on > 0) {                       /* slot k's stage i: unit 4k+i */\n")
rep(f, "    int cur, nslot;\n    GLuint tset[TM_SLOTS][4];\n    GLint dslot[MG_DRAWS];\n} s_mg;",
    "    int cur, nslot;\n    GLuint tset[TM_SLOTS][4];\n    GLint dslot[MG_DRAWS];\n"
    "    float sc0[TM_SLOTS][8][4], sc1[TM_SLOTS][8][4];   /* each slot's combiner constants */\n"
    "    int cdefer;                             /* slot 0's were replaced in p->uni */\n"
    "} s_mg;")
rep(f, "    s_mg.dslot[0] = 0;\n    s_mg.cur = 0;\n    s_mg.nslot = 1;\n",
    "    s_mg.dslot[0] = 0;\n    s_mg.cur = 0;\n    s_mg.nslot = 1;\n"
    "    memcpy(s_mg.sc0[0], p->uni.c0, sizeof s_mg.sc0[0]);\n"
    "    memcpy(s_mg.sc1[0], p->uni.c1, sizeof s_mg.sc1[0]);\n")
# Slot matching: textures and constants.
rep(f, '''static int tm_can_fold(const GlProg *p)
{
    int k;
    if (!s_tex_diff)
        return 1;
    if (!p->tslot || s_want_mask != 0xF || s_mg.nd >= MG_DRAWS)
        return 0;
    for (k = 0; k < s_mg.nslot; k++)
        if (!memcmp(s_mg.tset[k], s_want, sizeof s_want))
            return 1;
    return s_mg.nslot < TM_SLOTS;
}''', '''static int tm_slot_match(int k, const GlProg *p)
{
    return !memcmp(s_mg.tset[k], s_want, sizeof s_want)
           && !memcmp(s_mg.sc0[k], p->uni.c0, sizeof s_mg.sc0[k])
           && !memcmp(s_mg.sc1[k], p->uni.c1, sizeof s_mg.sc1[k]);
}
static int tm_can_fold(const GlProg *p)
{
    int k;
    if (!s_tex_diff && !s_cdiff)
        return 1;
    if (!p->tslot || s_want_mask != 0xF || s_mg.nd >= MG_DRAWS)
        return 0;
    for (k = 0; k < s_mg.nslot; k++)
        if (tm_slot_match(k, p))
            return 1;
    return s_mg.nslot < TM_SLOTS;
}''')
rep(f, '''static void tm_take(void)
{
    int k, i;
    if (s_tex_diff) {
        for (k = 0; k < s_mg.nslot && memcmp(s_mg.tset[k], s_want, sizeof s_want); k++) { }
        if (k == s_mg.nslot) {
            s_mg.nslot++;
            memcpy(s_mg.tset[k], s_want, sizeof s_want);''', '''static void tm_take(const GlProg *p)
{
    int k, i;
    if (s_tex_diff || s_cdiff) {
        for (k = 0; k < s_mg.nslot && !tm_slot_match(k, p); k++) { }
        if (k == s_mg.nslot) {
            s_mg.nslot++;
            memcpy(s_mg.tset[k], s_want, sizeof s_want);
            memcpy(s_mg.sc0[k], p->uni.c0, sizeof s_mg.sc0[k]);
            memcpy(s_mg.sc1[k], p->uni.c1, sizeof s_mg.sc1[k]);''')
rep(f, "            tm_take();\n", "            tm_take(p);\n", count=2)
rep(f, "        if (s_tex_diff && !tm_can_fold(p))\n            s_draw_changed |= DC_TEX;\n",
    "        if ((s_tex_diff || s_cdiff) && !tm_can_fold(p))\n"
    "            s_draw_changed |= s_tex_diff ? DC_TEX : DC_UNI;\n")
# Flush: every slot's constants; afterwards slot 0 gets the latest draw's.
rep(f, "        if (s_mg.nslot > 1)\n            p_glUniform1iv(mp->u_dslot, s_mg.nd, s_mg.dslot);",
    "        if (s_mg.nslot > 1) {\n"
    "            p_glUniform1iv(mp->u_dslot, s_mg.nd, s_mg.dslot);\n"
    "            if (mp->u_c0 >= 0)\n"
    "                p_glUniform4fv(mp->u_c0, s_mg.nslot * 8, &s_mg.sc0[0][0][0]);\n"
    "            if (mp->u_c1 >= 0)\n"
    "                p_glUniform4fv(mp->u_c1, s_mg.nslot * 8, &s_mg.sc1[0][0][0]);\n"
    "        }")
rep(f, "    s_mg.permat = s_mg.defer = 0;\n    s_mg.nslot = 1;\n",
    "    if (mp && s_mg.cdefer) {            /* slot 0 back to the latest draw's */\n"
    "        if (mp->u_c0 >= 0)\n"
    "            p_glUniform4fv(mp->u_c0, mp->n_c0, &mp->uni.c0[0][0]);\n"
    "        if (mp->u_c1 >= 0)\n"
    "            p_glUniform4fv(mp->u_c1, mp->n_c1, &mp->uni.c1[0][0]);\n"
    "    }\n"
    "    s_mg.cdefer = 0;\n"
    "    s_mg.permat = s_mg.defer = 0;\n    s_mg.nslot = 1;\n")
# Unread constant rows are not a change.
rep(f, '''            if (!fogd) {
                memcpy(u.mv, p->uni.mv, sizeof u.mv);
                memcpy(u.fogplane, p->uni.fogplane, sizeof u.fogplane);
            }
        }
''', '''            if (!fogd) {
                memcpy(u.mv, p->uni.mv, sizeof u.mv);
                memcpy(u.fogplane, p->uni.fogplane, sizeof u.fogplane);
            }
            {   /* combiner constant rows the pixel shader never reads: stage i
                 * reads row i when per-stage constants are on, else row 0 */
                uint32_t cnt = p->pkey.control & 0xFF, r0, r1;
                if (cnt > 8)
                    cnt = 8;
                r0 = p->u_c0 < 0 ? 0 : (p->pkey.control & (1u << 12)) ? cnt : 1;
                r1 = p->u_c1 < 0 ? 0 : (p->pkey.control & (1u << 16)) ? cnt : 1;
                if (r0 < 8)
                    memcpy(u.c0[r0], p->uni.c0[r0], (8 - r0) * sizeof u.c0[0]);
                if (r1 < 8)
                    memcpy(u.c1[r1], p->uni.c1[r1], (8 - r1) * sizeof u.c1[0]);
            }
        }
''')
# Constants (and maybe matrices) differ: defer them into a slot.
rep(f, '''            if (!memcmp(&t2, &p->uni, sizeof t2)) {
                p->uni = u;
                s_mg.defer = 1;
            }
        }
''', '''            if (!memcmp(&t2, &p->uni, sizeof t2)) {
                p->uni = u;
                s_mg.defer = 1;
            }
        }
        if (s_tm_on > 0 && p->uni_valid && s_mg_active && s_mg.prog == p && p->tslot
            && !s_draw_changed && s_mg.nd < MG_DRAWS && memcmp(&u, &p->uni, sizeof u) != 0) {
            /* The combiner constants differ (and perhaps the matrices): this
             * draw may fold with a texture slot carrying them (tm_take); the
             * flush uploads every slot's, then the latest back in slot 0. */
            struct GlUni t2 = u;
            int mat = p->permat && u.xform == 1;
            memcpy(t2.c0, p->uni.c0, sizeof t2.c0);
            memcpy(t2.c1, p->uni.c1, sizeof t2.c1);
            if (mat) {
                memcpy(t2.m, p->uni.m, sizeof t2.m);
                memcpy(t2.mv, p->uni.mv, sizeof t2.mv);
            }
            if (!memcmp(&t2, &p->uni, sizeof t2)) {
                if (memcmp(u.m, p->uni.m, sizeof u.m) || memcmp(u.mv, p->uni.mv, sizeof u.mv))
                    s_mg.defer = 1;
                if (memcmp(u.c0, p->uni.c0, sizeof u.c0) || memcmp(u.c1, p->uni.c1, sizeof u.c1)) {
                    s_cdiff = 1;
                    s_mg.cdefer = 1;
                }
                p->uni = u;
            }
        }
''')

for n, p in P.items():
    p.write_text(T[n])
print("ok")

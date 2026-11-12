#!/usr/bin/env python3
"""Draws that differ from the held one only in their textures fold into the
same GL call (RECOMP_GL_TEXMERGE; on by default on the web).

Why: in MC3 races about 200 of ~1,050 draws per frame could not merge only
because a texture changed, and on Chrome every draw call costs the GPU
process (CPU-bound there; the GPU itself sat at ~16%).

How:
- A merged call can use up to 4 texture sets ("slots"): slot k's stage i
  texture sits on unit 4k+i (slot 0 = units 0-3, as before).
- Each draw set in a merged call (the existing per-draw matrix sets, u_dend)
  gets a slot index, u_dslot[set]; the vertex shader passes it to the
  fragment shader (flat int vDslot), which samples tN, tN_1, tN_2 or tN_3.
  Gradients are taken before the choice (textureGrad), so mip selection is
  defined even where neighbouring pixels belong to different draws.
- While a draw is held, a new draw's texture binds are held back (s_want):
  binding them would end the held call. If the draw folds, its textures go
  to a slot's units; if not, the held call goes out and they are bound to
  units 0-3 as usual (want_apply, at the end of merge_flush).
- A texture whose sampler settings must change ends the held call first
  (sampler settings live in the texture object).
- Slot units are cleared when the draw target changes, so a texture left
  there can never be the render target (WebGL refuses such feedback loops
  for any sampler the program could read).
- Programs with dependent texture reads (modes 15/16) or without per-draw
  sets (ANGLE's gl_VertexID fallback prelude) never take slots."""
import pathlib, sys

src = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl"
P = {n: src / n for n in ["nv2a_gl.c", "gl_vsh.c", "gl_vsh.h", "gl_psh.c"]}
T = {n: p.read_text() for n, p in P.items()}
if "RECOMP_GL_TEXMERGE" in T["nv2a_gl.c"]:
    print("already"); sys.exit(0)

def rep(f, a, b, count=1):
    s = T[f]
    assert s.count(a) == count, (f, a[:80], s.count(a))
    T[f] = s.replace(a, b)

# ── gl_vsh.h / gl_vsh.c ─────────────────────────────────────────────────
rep("gl_vsh.h", "extern int nv2a_shader_vk;\n",
    "extern int nv2a_shader_vk;\n"
    "extern int nv2a_gl_tslots;      /* texture slots per merged draw (nv2a_gl.c texmerge) */\n")
rep("gl_vsh.c", "\nint nv2a_shader_vk;\n",
    "\nint nv2a_shader_vk;\nint nv2a_gl_tslots;\n")
rep("gl_vsh.c", "/* Asked for (RECOMP_GL_CUBO=1) and possible:",
    '''/* Texture slots (nv2a_gl.c, texmerge): each draw of a merged call names
 * its slot, u_dslot[set], and the pixel shader samples that slot's
 * textures. */
static char *with_dslot(const char *src)
{
    static const char at_s[] = "int nv2a_di;\\n";
    static const char add[] = "uniform int u_dslot[16];\\nflat out int vDslot;\\n#define NV2A_DSLOT 1\\n";
    const char *at = strstr(src, at_s);
    size_t b = strlen(add), n = strlen(src);
    char *o;
    if (!at || !(o = (char *)malloc(n + b + 1)))
        return NULL;
    memcpy(o, src, (size_t)(at - src));
    memcpy(o + (at - src), add, b);
    memcpy(o + (at - src) + b, at, n - (size_t)(at - src) + 1);
    return o;
}

/* Asked for (RECOMP_GL_CUBO=1) and possible:''')
rep("gl_vsh.c", "        prelude = (char *)p;\n",
    "        if (nv2a_gl_tslots && (t = with_dslot(p)) != NULL)\n"
    "            p = t;\n"
    "        prelude = (char *)p;\n")
rep("gl_vsh.c", '    set_ib \\\n',
    '    set_ib \\\n'
    '    "#ifdef NV2A_DSLOT\\n    vDslot = u_dslot[nv2a_draw_index() / 4];\\n#endif\\n" \\\n')
rep("gl_vsh.c", '        "    nv2a_di = nv2a_draw_index();\\n"\n',
    '        "    nv2a_di = nv2a_draw_index();\\n"\n'
    '        "#ifdef NV2A_DSLOT\\n    vDslot = u_dslot[nv2a_di / 4];\\n#endif\\n"\n')

# ── gl_psh.c ────────────────────────────────────────────────────────────
rep("gl_psh.c", "static void tex_fetch(Out *o, int t, uint32_t mode, const Nv2aPshKey *k)\n{",
    "extern int nv2a_gl_tslots;\n"
    "#define TSLOT_DECL \\\n"
    "    \"flat in int vDslot;\\n\" \\\n"
    "    \"uniform sampler2D t0_1; uniform sampler2D t1_1; uniform sampler2D t2_1; uniform sampler2D t3_1;\\n\" \\\n"
    "    \"uniform sampler2D t0_2; uniform sampler2D t1_2; uniform sampler2D t2_2; uniform sampler2D t3_2;\\n\" \\\n"
    "    \"uniform sampler2D t0_3; uniform sampler2D t1_3; uniform sampler2D t2_3; uniform sampler2D t3_3;\\n\"\n"
    "static void tex_fetch(Out *o, int t, uint32_t mode, const Nv2aPshKey *k)\n{")
rep("gl_psh.c",
    '        emit(o, "    vec4 T%d = texture(t%d, tc%d * u_tscale[%d]);\\n", t, t, t, t);\n        break;\n',
    '''        if (nv2a_gl_tslots && !nv2a_shader_vk) {
            /* The draw's texture slot (nv2a_gl.c, texmerge). Gradients first,
             * outside the choice: mip selection stays defined where the
             * pixels of a 2x2 block belong to different draws. */
            emit(o, "    vec2 uv%d = tc%d * u_tscale[%d], gx%d = dFdx(uv%d), gy%d = dFdy(uv%d);\\n",
                 t, t, t, t, t, t, t);
            emit(o, "    vec4 T%d = vDslot == 0 ? textureGrad(t%d, uv%d, gx%d, gy%d)\\n"
                    "           : vDslot == 1 ? textureGrad(t%d_1, uv%d, gx%d, gy%d)\\n"
                    "           : vDslot == 2 ? textureGrad(t%d_2, uv%d, gx%d, gy%d)\\n"
                    "           : textureGrad(t%d_3, uv%d, gx%d, gy%d);\\n",
                 t, t, t, t, t, t, t, t, t, t, t, t, t, t, t, t, t);
        } else
            emit(o, "    vec4 T%d = texture(t%d, tc%d * u_tscale[%d]);\\n", t, t, t, t);
        break;
''')
# The GL header literal: room for the slot declarations (no % in it before).
i = T["gl_psh.c"].index('        "uniform sampler2D t2; uniform sampler2D t3;\\n"\n        "uniform vec2 u_tscale[4];\\n"')
j = T["gl_psh.c"].index('        "void main() {\\n");\n    for (i = 0; i < 4; i++)\n        tex_fetch', i)
assert "%" not in T["gl_psh.c"][i:j], "a % in the GL header"
rep("gl_psh.c", '        "uniform sampler2D t2; uniform sampler2D t3;\\n"\n        "uniform vec2 u_tscale[4];\\n"',
    '        "uniform sampler2D t2; uniform sampler2D t3;\\n"\n        "%s"\n        "uniform vec2 u_tscale[4];\\n"')
rep("gl_psh.c", '        "void main() {\\n");\n    for (i = 0; i < 4; i++)\n        tex_fetch',
    '        "void main() {\\n", nv2a_gl_tslots ? TSLOT_DECL : "");\n    for (i = 0; i < 4; i++)\n        tex_fetch')

# ── nv2a_gl.c ───────────────────────────────────────────────────────────
f = "nv2a_gl.c"
rep(f, "static uint32_t s_pf_permat, s_pf_permat_calls;   /* draws folded with their own matrices */\n",
    "static uint32_t s_pf_permat, s_pf_permat_calls;   /* draws folded with their own matrices */\n"
    "static uint32_t s_pf_texfold;                     /* ... with their own textures (texmerge) */\n")
rep(f, "static GLuint s_bound[4];\n",
    "static GLuint s_bound[16];      /* 0-3 the stages; 4-15 texture slots (texmerge) */\n")
rep(f, "    if (u >= 0 && u < 4 && (s_bound_known & (1 << u)) && s_bound[u] == tex)\n",
    "    if (u >= 0 && u < 16 && (s_bound_known & (1 << u)) && s_bound[u] == tex)\n")
rep(f, "    glBindTexture(GL_TEXTURE_2D, tex);\n    if (u >= 0 && u < 4) {\n",
    "    glBindTexture(GL_TEXTURE_2D, tex);\n    if (u >= 0 && u < 16) {\n")
rep(f, "/* ── Surfaces ──────────────────────────────────────────────────────── */",
    r'''/* Texture slots (texmerge, RECOMP_GL_TEXMERGE): a merged call may carry up
 * to TM_SLOTS texture sets; slot k's stage i on unit 4k+i. */
#define TM_SLOTS 4
static int s_tm_on = -1;
static GLuint s_want[4];        /* a held-back draw's stage textures */
static int s_want_mask;         /* ... which stages are held back */
static int s_tex_diff;          /* ... and they differ from the held call's latest set */
static uint32_t s_slot_dirty;   /* slot units holding a texture */
static int tm_dependent(const Nv2aPshKey *k)
{
    int t;
    for (t = 0; t < 4; t++) {
        uint32_t m = (k->shader_program >> (5 * t)) & 0x1F;
        if (m == 15 || m == 16)
            return 1;
    }
    return 0;
}
/* Bind on a slot unit without ending the held call: the held call does not
 * read that slot (yet). */
static void bind_unit_raw(int u, GLuint tex)
{
    active_unit(u);
    if (((s_bound_known >> u) & 1) && s_bound[u] == tex)
        return;
    p_glBindTexture(GL_TEXTURE_2D, tex);
    s_bound[u] = tex;
    s_bound_known |= 1 << u;
    if (tex)
        s_slot_dirty |= 1u << u;
    else
        s_slot_dirty &= ~(1u << u);
}
/* A new draw target: no slot unit may hold what is now drawn into. */
static void tm_unbind_slots(void)
{
    int u;
    for (u = 4; u < 16; u++)
        if (s_slot_dirty & (1u << u))
            bind_unit_raw(u, 0);
}

/* ── Surfaces ──────────────────────────────────────────────────────── */''')
rep(f, "    glBindFramebuffer(GL_FRAMEBUFFER, s->fbo);\n    if (s_shared_z < 0) {",
    "    if (s_slot_dirty && s_mg_fb_draw != s->fbo) {\n"
    "        glBindFramebuffer(GL_FRAMEBUFFER, s->fbo);    /* ends a held call first */\n"
    "        tm_unbind_slots();\n"
    "    }\n"
    "    glBindFramebuffer(GL_FRAMEBUFFER, s->fbo);\n    if (s_shared_z < 0) {")
rep(f, "static void bind_stage(const uint32_t *regs, int i, float scale[2])\n{",
    "static void stage_tex(int i, GLuint tex);\nstatic void stage_realize(int i);\n"
    "static void bind_stage(const uint32_t *regs, int i, float scale[2])\n{")
rep(f, "        bind_tex(0);\n        return;\n    }\n    va = s_batch->tex_va[i];",
    "        stage_tex(i, 0);\n        return;\n    }\n    va = s_batch->tex_va[i];")
rep(f, "    if (!w || !h || w > 4096 || h > 4096) {\n        bind_tex(0);\n        return;\n    }",
    "    if (!w || !h || w > 4096 || h > 4096) {\n        stage_tex(i, 0);\n        return;\n    }")
rep(f, "    bind_tex(tex);\n    {\n        /* Sampler state lives in the texture object",
    "    stage_tex(i, tex);\n    {\n        /* Sampler state lives in the texture object")
rep(f, "        if (tp->id != tex || tp->key != key) {\n            s_draw_changed |= DC_SAMP;",
    "        if (tp->id != tex || tp->key != key) {\n            stage_realize(i);           /* bound for real: its settings change */\n"
    "            s_draw_changed |= DC_SAMP;")
rep(f, "    GLint      u_dend;          /* per-draw matrices of a merged call (gl_vsh.c) */\n",
    "    GLint      u_dend;          /* per-draw matrices of a merged call (gl_vsh.c) */\n"
    "    GLint      u_dslot;         /* per-draw texture slot (texmerge) */\n"
    "    int        tslot;           /* ... usable */\n")
rep(f, '    p->vpc_rows = p->u_c >= 0 && glGetUniformLocation(p->prog, "c[191]") == p->u_c + 191;\n',
    '    p->u_dslot = glGetUniformLocation(p->prog, "u_dslot");\n'
    '    p->tslot = s_tm_on > 0 && p->u_dslot >= 0 && p->u_dend >= 0\n'
    '               && arr_active(p->prog, "u_dslot", MG_DRAWS) == MG_DRAWS\n'
    '               && arr_active(p->prog, "u_dend", MG_DRAWS) == MG_DRAWS && !tm_dependent(pk);\n'
    '    p->vpc_rows = p->u_c >= 0 && glGetUniformLocation(p->prog, "c[191]") == p->u_c + 191;\n')
rep(f, "    if (p->u_dend >= 0)\n        glUniform1i(p->u_dend, 0x7FFFFFFF);    /* one draw: set 0 */\n    return p;",
    "    if (s_tm_on > 0) {                       /* slot k's stage i: unit 4k+i */\n"
    "        int k;\n"
    "        for (k = 1; k < TM_SLOTS; k++)\n"
    "            for (i = 0; i < 4; i++) {\n"
    "                char n[8];\n"
    "                GLint u;\n"
    "                snprintf(n, sizeof n, \"t%d_%d\", i, k);\n"
    "                u = glGetUniformLocation(p->prog, n);\n"
    "                if (u >= 0)\n"
    "                    glUniform1i(u, 4 * k + i);\n"
    "            }\n"
    "    }\n"
    "    if (p->u_dend >= 0)\n        glUniform1i(p->u_dend, 0x7FFFFFFF);    /* one draw: set 0 */\n    return p;")
rep(f, "    GLint bv;                               /* base vertex (lean draws), or -1 */\n} s_mg;",
    "    GLint bv;                               /* base vertex (lean draws), or -1 */\n"
    "    /* Texture slots (texmerge): the sets of textures in this call, the\n"
    "     * latest one, and each draw set's slot (u_dslot). */\n"
    "    int cur, nslot;\n"
    "    GLuint tset[TM_SLOTS][4];\n"
    "    GLint dslot[MG_DRAWS];\n"
    "} s_mg;")
rep(f, "        memcpy(s_mg.pmv[j], p->uni.mv, sizeof s_mg.pmv[j]);\n    }\n    s_mg.dend[j] = (GLint)s_mg.last_end;",
    "        memcpy(s_mg.pmv[j], p->uni.mv, sizeof s_mg.pmv[j]);\n        s_mg.dslot[j] = s_mg.cur;\n    }\n    s_mg.dend[j] = (GLint)s_mg.last_end;")
rep(f, "    s_mg.dend[0] = (GLint)nv;\n}\n",
    r'''    s_mg.dend[0] = (GLint)nv;
    s_mg.dslot[0] = 0;
    s_mg.cur = 0;
    s_mg.nslot = 1;
    {
        int i;
        for (i = 0; i < 4; i++)
            s_mg.tset[0][i] = ((s_bound_known >> i) & 1) ? s_bound[i] : 0xFFFFFFFFu;
    }
}

/* Held-back texture binds (texmerge): onto units 0-3 now. */
static void want_apply(void)
{
    int i, m = s_want_mask;
    s_want_mask = 0;
    for (i = 0; i < 4; i++)
        if (m & (1 << i)) {
            active_unit(i);
            bind_tex(s_want[i]);
        }
}
/* A stage's texture for this draw: held back while a call is held (it may
 * fold with a slot of its own), bound at once otherwise. */
static void stage_tex(int i, GLuint tex)
{
    if (s_tm_on > 0 && s_mg_active) {
        s_want[i] = tex;
        s_want_mask |= 1 << i;
        if (tex != s_mg.tset[s_mg.cur][i])
            s_tex_diff = 1;
        return;
    }
    s_want_mask &= ~(1 << i);
    active_unit(i);
    bind_tex(tex);
}
/* Stage i's texture must really be bound (its settings change). */
static void stage_realize(int i)
{
    if (s_want_mask & (1 << i)) {
        merge_flush();
        want_apply();
        active_unit(i);
    }
}
/* Could this draw fold with its textures? Same set as the latest: yes;
 * else a program that takes slots, room for a set, and a slot to use. */
static int tm_can_fold(const GlProg *p)
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
}
/* It folds: its textures to their slot, and a draw set of its own. */
static void tm_take(void)
{
    int k, i;
    if (s_tex_diff) {
        for (k = 0; k < s_mg.nslot && memcmp(s_mg.tset[k], s_want, sizeof s_want); k++) { }
        if (k == s_mg.nslot) {
            s_mg.nslot++;
            memcpy(s_mg.tset[k], s_want, sizeof s_want);
            for (i = 0; i < 4; i++)
                bind_unit_raw(4 * k + i, s_want[i]);
        }
        s_mg.cur = k;
        s_mg.defer = 1;                 /* merge_note: a new set */
        s_pf_texfold++;
    }
    s_want_mask = 0;
}
''')
rep(f, "        p_glUniform4fv(mp->u_m, s_mg.nd * 4, &s_mg.pm[0][0]);\n        if (mp->u_mv >= 0)\n            p_glUniform4fv(mp->u_mv, s_mg.nd * 4, &s_mg.pmv[0][0]);\n        p_glUniform1iv(mp->u_dend, s_mg.nd, s_mg.dend);",
    "        if (mp->permat) {\n"
    "            p_glUniform4fv(mp->u_m, s_mg.nd * 4, &s_mg.pm[0][0]);\n"
    "            if (mp->u_mv >= 0)\n"
    "                p_glUniform4fv(mp->u_mv, s_mg.nd * 4, &s_mg.pmv[0][0]);\n"
    "        }\n"
    "        p_glUniform1iv(mp->u_dend, s_mg.nd, s_mg.dend);\n"
    "        if (s_mg.nslot > 1)\n"
    "            p_glUniform1iv(mp->u_dslot, s_mg.nd, s_mg.dslot);")
rep(f, "        p_glUniform1i(mp->u_dend, 0x7FFFFFFF);\n    }\n    s_mg.permat = s_mg.defer = 0;",
    "        p_glUniform1i(mp->u_dend, 0x7FFFFFFF);\n"
    "        if (s_mg.nslot > 1)\n"
    "            p_glUniform1i(mp->u_dslot, 0);\n"
    "    }\n"
    "    s_mg.permat = s_mg.defer = 0;\n"
    "    s_mg.nslot = 1;\n"
    "    if (s_want_mask)                   /* the next draw's textures, held back */\n"
    "        want_apply();")
rep(f, "    s_draw_changed = 0;\n    s_draw_uf = 0;\n    s_mg_was_active = s_mg_active;\n",
    "    s_draw_changed = 0;\n    s_draw_uf = 0;\n    s_want_mask = 0;\n    s_tex_diff = 0;\n    s_mg_was_active = s_mg_active;\n")
rep(f, "        if (s_pf_on > 0)\n            merge_census(ml || sl,",
    "        if (s_tex_diff && !tm_can_fold(p))\n            s_draw_changed |= DC_TEX;\n"
    "        if (s_pf_on > 0)\n            merge_census(ml || sl,")
rep(f, "            && stage_append(b, &SL, srun, midx, mn)) {\n            s_pf_folded++;",
    "            && stage_append(b, &SL, srun, midx, mn)) {\n            tm_take();\n            s_pf_folded++;")
rep(f, "            && merge_append(b, midx, mn, &L)) {\n            s_pf_permat += s_mg.defer;",
    "            && merge_append(b, midx, mn, &L)) {\n            tm_take();\n            s_pf_permat += s_mg.defer;")
rep(f, '        fprintf(stderr, "%s rest %u; folded with own matrices %u (in %u calls)\\n", line,\n                s_census_other / fr, s_pf_permat / fr, s_pf_permat_calls / fr);\n        s_pf_permat = s_pf_permat_calls = 0;',
    '        fprintf(stderr, "%s rest %u; folded with own matrices %u (in %u calls), with own textures %u\\n",\n'
    '                line, s_census_other / fr, s_pf_permat / fr, s_pf_permat_calls / fr,\n'
    '                s_pf_texfold / fr);\n'
    '        s_pf_permat = s_pf_permat_calls = s_pf_texfold = 0;')
rep(f, "        nv2a_gl_vsh_cubo_set(s_cubo_on);\n",
    r'''        nv2a_gl_vsh_cubo_set(s_cubo_on);
        {
            const char *t = getenv("RECOMP_GL_TEXMERGE");
            GLint units = 0;
#if defined(__EMSCRIPTEN__)
            int def = 1;
#else
            int def = 0;
#endif
            glGetIntegerv(0x8872 /* GL_MAX_TEXTURE_IMAGE_UNITS */, &units);
            s_tm_on = (t ? t[0] == '1' : def) && units >= 16 && !nv2a_shader_vk;
            nv2a_gl_tslots = s_tm_on;
            fprintf(stderr, "  [GL] draws that differ only in textures %s (RECOMP_GL_TEXMERGE)\n",
                    s_tm_on ? "fold, up to 4 texture sets per call" : "do not fold");
        }
''')

for n, p in P.items():
    p.write_text(T[n])
print("ok")

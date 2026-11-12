#!/usr/bin/env python3
"""WebGL 2 on the GL thread without SDL's window (nv2a_gl.c, Emscripten only).

SDL's Emscripten port makes its GL context through EGL, which Emscripten
runs on the page's main thread -- where the canvas no longer is, since the
GL thread owns it as an OffscreenCanvas. So on the web the GL thread makes
its own WebGL 2 context, the few SDL_GL_* calls map onto Emscripten's, and
the queue is drained from a requestAnimationFrame loop that hands control
back to the browser after every flip: a worker's OffscreenCanvas shows a
frame only when the worker returns to its event loop."""
import pathlib, sys
root = pathlib.Path.home() / "mc3-web"
p = root / "xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "q_web_tick" in s:
    print("already applied"); sys.exit(0)

# 1. SDL_GL_* -> Emscripten, right after <SDL.h>
SHIM = r'''
#if defined(__EMSCRIPTEN__)
/* The browser: WebGL 2 on the GL thread's OffscreenCanvas (see gl_make_window). */
#include <emscripten.h>
#include <emscripten/html5.h>
#include <emscripten/html5_webgl.h>
const unsigned char *emscripten_glGetString(unsigned int name);
static int web_gl_has_ext(const char *name)
{
    const char *all = (const char *)emscripten_glGetString(0x1F03);   /* GL_EXTENSIONS */
    size_t n = strlen(name);
    const char *p = all;
    while (p && (p = strstr(p, name)) != NULL) {
        if ((p == all || p[-1] == ' ') && (p[n] == ' ' || p[n] == 0))
            return 1;
        p += n;
    }
    return 0;
}
static void *web_gl_proc(const char *name) { return emscripten_webgl_get_proc_address(name); }
#define SDL_GL_MakeCurrent(w, c) \
    (emscripten_webgl_make_context_current((EMSCRIPTEN_WEBGL_CONTEXT_HANDLE)(uintptr_t)(c)) \
        == EMSCRIPTEN_RESULT_SUCCESS ? 0 : -1)
#define SDL_GL_SwapWindow(w)           ((void)(w))      /* presented when the tick returns */
#define SDL_GL_SetSwapInterval(i)      ((void)(i), 0)
#define SDL_GL_GetDrawableSize(w, pw, ph) \
    ((void)(w), (void)emscripten_get_canvas_element_size("#canvas", (pw), (ph)))
#define SDL_GL_ExtensionSupported(n)   web_gl_has_ext(n)
#define SDL_GL_GetProcAddress          web_gl_proc
#endif
'''
anchor = "#include <SDL.h>\n"
assert anchor in s
s = s.replace(anchor, anchor + SHIM, 1)

# 2. The context: WebGL 2 on this thread's canvas.
old = "static void gl_make_window(void *unused)\n{\n"
assert old in s
s = s.replace(old, '''static void gl_make_window(void *unused)
{
#if defined(__EMSCRIPTEN__)
    EmscriptenWebGLContextAttributes a;
    EMSCRIPTEN_WEBGL_CONTEXT_HANDLE c;
    (void)unused;
    emscripten_webgl_init_context_attributes(&a);
    a.majorVersion = 2;
    a.minorVersion = 0;
    a.alpha = 0;
    a.depth = 1;
    a.stencil = 1;
    a.antialias = 0;
    a.premultipliedAlpha = 0;
    a.powerPreference = EM_WEBGL_POWER_PREFERENCE_HIGH_PERFORMANCE;
    emscripten_set_canvas_element_size("#canvas", 1280, 720);
    c = emscripten_webgl_create_context("#canvas", &a);
    if (c <= 0) {
        fprintf(stderr, "  [GL] WebGL 2 context: error %d\\n", (int)c);
        return;
    }
    emscripten_webgl_make_context_current(c);
    nv2a_gl_es = 1;
    s_es_minor = 0;
    s_win = (SDL_Window *)(uintptr_t)1;          /* no SDL window on the web */
    s_ctx = (SDL_GLContext)(uintptr_t)c;
    fprintf(stderr, "  [GL] WebGL 2 context %d on the GL thread\\n", (int)c);
    return;
#endif
''', 1)

# 3. The GL thread: drained from requestAnimationFrame, one flip per tick.
i = s.index("static void *q_gl_thread(void *arg)\n{")
body_start = s.index("        rec = s_q + s_q_tail % Q_BYTES;\n", i)
body_end = s.index("    }\n    return NULL;\n}", body_start)
body = s[body_start:body_end]
body = body.replace("        h = (const QHdr *)rec;\n",
                    "        h = (const QHdr *)rec;\n        was_flip = h->type == Q_FLIP;\n", 1)
TICK = '''#if defined(__EMSCRIPTEN__)
/* One requestAnimationFrame's worth: everything queued up to and including
 * a flip, then back to the browser, which shows the frame. */
static void q_web_tick(void)
{
    for (;;) {
        size_t avail = __atomic_load_n(&s_q_head, __ATOMIC_SEQ_CST) - s_q_tail;
        uint8_t *rec;
        const QHdr *h;
        size_t at;
        uint32_t i;
        int was_flip;

        if (!avail) {
            merge_flush();
            return;
        }
''' + body + '''        if (was_flip)
            return;
    }
}
#endif

'''
s = s[:i] + TICK + s[i:]
old = "    xbox_nx_track_thread((void *)q_gl_thread);\n    for (;;) {"
assert old in s
s = s.replace(old, "    xbox_nx_track_thread((void *)q_gl_thread);\n"
                   "#if defined(__EMSCRIPTEN__)\n"
                   "    if (!ready())\n"
                   "        fprintf(stderr, \"  [GL] no WebGL 2: nothing will be drawn\\n\");\n"
                   "    emscripten_set_main_loop(q_web_tick, 0, 1);   /* does not return */\n"
                   "#endif\n"
                   "    for (;;) {", 1)
p.write_text(s)
print("ok nv2a_gl.c")

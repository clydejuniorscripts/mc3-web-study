#!/usr/bin/env python3
"""GL thread loop, third form (WEB_GL_LOOP=port, the new default).

After a flip the worker must return to its event loop for the OffscreenCanvas
to present. Coming back through a MessageChannel message is immediate, where
a chained setTimeout is clamped to >= 4 ms. When the queue runs dry mid-frame
the thread first waits (up to ~6 ms) on the queue's condition variable for the
executor's next commands instead of leaving, and only goes back to the
browser (setTimeout 0) when nothing comes. raf / timer stay selectable."""
import pathlib, sys
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "web_gl_port_loop" in s:
    print("already"); sys.exit(0)

def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:70], s.count(a))
    s = s.replace(a, b, 1)

# 1. The tick reports a flip, and may wait for more work when the queue is dry.
rep("static void q_web_tick(void)\n{\n    s_web_ticks++;\n",
    "static int s_web_flipped;        /* the last tick ended at a flip */\n"
    "static int s_web_wait_dry;       /* port mode: wait for work before leaving */\n"
    "static void q_web_tick(void)\n{\n    s_web_ticks++;\n    s_web_flipped = 0;\n")
rep("        if (!avail) {\n            merge_flush();\n            return;\n        }\n        rec = s_q + s_q_tail % Q_BYTES;\n        h = (const QHdr *)rec;\n        was_flip = h->type == Q_FLIP;",
    "        if (!avail) {\n            merge_flush();\n"
    "            if (s_web_wait_dry) {      /* the rest of the frame is usually a moment away */\n"
    "                int tries = 0;\n"
    "                pthread_mutex_lock(&s_q_lock);\n"
    "                __atomic_store_n(&s_q_consumer_waits, 1, __ATOMIC_SEQ_CST);\n"
    "                while (__atomic_load_n(&s_q_head, __ATOMIC_SEQ_CST) == s_q_tail && tries++ < 3)\n"
    "                    q_timed_wait();\n"
    "                __atomic_store_n(&s_q_consumer_waits, 0, __ATOMIC_SEQ_CST);\n"
    "                pthread_mutex_unlock(&s_q_lock);\n"
    "                if (__atomic_load_n(&s_q_head, __ATOMIC_SEQ_CST) != s_q_tail)\n"
    "                    continue;\n"
    "            }\n"
    "            return;\n        }\n        rec = s_q + s_q_tail % Q_BYTES;\n        h = (const QHdr *)rec;\n        was_flip = h->type == Q_FLIP;")
rep("        if (was_flip) {\n            s_web_flips_done++;\n            return;\n        }",
    "        if (was_flip) {\n            s_web_flips_done++;\n            s_web_flipped = 1;\n            return;\n        }")

# 2. The JS loop and its entry point, after q_web_tick.
anchor = "static void *q_gl_thread(void *arg)\n{"
rep(anchor, r'''#if defined(__EMSCRIPTEN__)
/* One turn of the port loop: 1 when it ended at a flip (come back at once). */
EMSCRIPTEN_KEEPALIVE int web_gl_tick(void)
{
    q_web_tick();
    return s_web_flipped;
}
EM_JS(void, web_gl_port_loop, (void), {
    var ch = new MessageChannel();
    var turn = function() {
        var flipped = _web_gl_tick();
        if (flipped) ch.port2.postMessage(0);      /* present, then straight back */
        else setTimeout(turn, 0);                  /* nothing queued: let the browser idle */
    };
    ch.port1.onmessage = turn;
    ch.port2.postMessage(0);
});
#endif

''' + anchor)

# 3. Choose the loop.
rep("""        const char *e = getenv("WEB_GL_LOOP");
        int raf = e && !strcmp(e, "raf");   /* timer: 23-24 fps in races vs 19.8 */
        fprintf(stderr, "  [GL] queue drained %s (WEB_GL_LOOP)\\n",
                raf ? "at each animation frame" : "from a 1 ms timer: frames shown when done");
        emscripten_set_main_loop(q_web_tick, raf ? 0 : 1000, 1);   /* does not return */""",
    """        const char *e = getenv("WEB_GL_LOOP");
        int raf = e && !strcmp(e, "raf"), timer = e && !strcmp(e, "timer");
        if (!raf && !timer) {
            fprintf(stderr, "  [GL] queue drained by a message loop: frames shown when done (WEB_GL_LOOP=port)\\n");
            s_web_wait_dry = 1;
            web_gl_port_loop();
            emscripten_unwind_to_js_event_loop();     /* the worker lives on */
        }
        fprintf(stderr, "  [GL] queue drained %s (WEB_GL_LOOP)\\n",
                raf ? "at each animation frame" : "from a 1 ms timer: frames shown when done");
        emscripten_set_main_loop(q_web_tick, raf ? 0 : 1000, 1);   /* does not return */""")
p.write_text(s)

c = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
t = c.read_text()
if "_web_gl_tick" not in t:
    t = t.replace("_web_audio_ring", "_web_audio_ring,_web_gl_tick")
    c.write_text(t)
print("ok")

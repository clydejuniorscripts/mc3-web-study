#!/usr/bin/env python3
"""Debug hooks callable from the page: the GL queue's state and a tick count."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/nv2a_gl/nv2a_gl.c"
s = p.read_text()
if "web_gl_state" in s:
    print("already")
else:
    a = "static void q_web_tick(void)\n{\n"
    assert a in s
    s = s.replace(a, """static volatile unsigned s_web_ticks, s_web_flips_done;
EMSCRIPTEN_KEEPALIVE void web_gl_state(void)
{
    fprintf(stderr, "  [GLSTATE] ticks %u flips %u | head %zu tail %zu queued %zu | flips queued %d"
            " producer_waits %d consumer_waits %d\\n",
            s_web_ticks, s_web_flips_done, (size_t)s_q_head, (size_t)s_q_tail,
            (size_t)(s_q_head - s_q_tail), (int)s_q_flips, (int)s_q_producer_waits,
            (int)s_q_consumer_waits);
}
static void q_web_tick(void)
{
    s_web_ticks++;
""", 1)
    s = s.replace("        if (was_flip)\n            return;\n    }\n}\n#endif",
                  "        if (was_flip) {\n            s_web_flips_done++;\n            return;\n        }\n    }\n}\n#endif", 1)
    p.write_text(s)
    print("ok")
c = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
t = c.read_text()
if "_web_gl_state" not in t:
    t = t.replace("-sEXPORTED_FUNCTIONS=_main,_web_pad_set,_xbox_sdl_keyboard_event",
                  "-sEXPORTED_FUNCTIONS=_main,_web_pad_set,_xbox_sdl_keyboard_event,_web_gl_state,_web_snapshot")
    c.write_text(t); print("exports ok")

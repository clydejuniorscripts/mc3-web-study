#!/usr/bin/env python3
"""Vblank catch-up: a vblank due while the timer thread waited for the guest
lock (more than half a period late) restarted the clock and was lost -- in
the browser 30% of them (42/s), which caps a 2-vblank game at 21 fps. With
RECOMP_VBLANK_CATCHUP=n (periods; web default 4) late vblanks are delivered
back to back instead, so the title's 60 Hz clock keeps its count."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/kernel/kernel_bridge.c"
s = p.read_text()
a = ("    if (now - s_vb_next_us > VBLANK_PERIOD_US / 2)\n"
     "        s_vb_next_us = now + VBLANK_PERIOD_US;    /* far behind: restart here */\n"
     "    else\n"
     "        s_vb_next_us += VBLANK_PERIOD_US;         /* on time: no drift */\n")
b = ("    {\n"
     "        static long long late_max = -1;      /* RECOMP_VBLANK_CATCHUP periods */\n"
     "        if (late_max < 0) {\n"
     "            const char *e = getenv(\"RECOMP_VBLANK_CATCHUP\");\n"
     "#if defined(__EMSCRIPTEN__)\n"
     "            int n = e ? atoi(e) : 4;\n"
     "#else\n"
     "            int n = e ? atoi(e) : 0;\n"
     "#endif\n"
     "            late_max = n > 0 ? (long long)n * VBLANK_PERIOD_US : VBLANK_PERIOD_US / 2;\n"
     "        }\n"
     "        if (now - s_vb_next_us > late_max)\n"
     "            s_vb_next_us = now + VBLANK_PERIOD_US;    /* far behind: restart here */\n"
     "        else\n"
     "            s_vb_next_us += VBLANK_PERIOD_US;         /* on time, or catching up */\n"
     "    }\n")
if "RECOMP_VBLANK_CATCHUP" in s:
    print("already")
else:
    assert s.count(a) == 1, s.count(a)
    p.write_text(s.replace(a, b, 1))
    print("ok")

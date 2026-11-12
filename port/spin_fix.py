#!/usr/bin/env python3
"""Spin before sleeping on the guest lock and the dispatch lock (web only).
A sleep-and-wake between browser workers (futex -> Atomics.wait/notify)
costs tens of microseconds; these locks are usually back within a few. The
main thread spent ~19% of a race in KfRaiseIrql/KfLowerIrql (DirectSound,
~1000 raises a second, each a contended hand-over at ~100 us). Spin up to
RECOMP_SPIN_US (default 50) first."""
import pathlib, sys
k = pathlib.Path.home() / "mc3-web/xboxrecomp/src/kernel"

SPIN = r'''
#if defined(__EMSCRIPTEN__)
#include <emscripten.h>
/* How long to spin for a lock before sleeping (RECOMP_SPIN_US, default 50). */
static double web_spin_ms(void)
{
    static double ms = -1;
    if (ms < 0) {
        const char *e = getenv("RECOMP_SPIN_US");
        ms = (e ? atof(e) : 50.0) / 1000.0;
    }
    return ms;
}
#endif
'''

# Guest lock (kernel_bridge.c, gil_lock).
p = k / "kernel_bridge.c"
s = p.read_text()
if "web_spin_ms" not in s:
    a = "static void gil_lock(void)\n{"
    assert s.count(a) == 1
    s = s.replace(a, SPIN + a, 1)
    b = ("    while (me != s_gil_serving)\n"
         "        if (!SleepConditionVariableCS(&s_gil_cv, &s_gil_cs, 1))\n")
    assert s.count(b) == 1, s.count(b)
    s = s.replace(b, ("#if defined(__EMSCRIPTEN__)\n"
                      "    if (me != s_gil_serving) {         /* spin a little before sleeping */\n"
                      "        double until = emscripten_get_now() + web_spin_ms();\n"
                      "        LeaveCriticalSection(&s_gil_cs);\n"
                      "        while (s_gil_serving != me && emscripten_get_now() < until) { }\n"
                      "        EnterCriticalSection(&s_gil_cs);\n"
                      "    }\n"
                      "#endif\n") + b, 1)
    p.write_text(s)
    print("ok gil")
else:
    print("already gil")

# Dispatch lock (kernel_hal.c, irql_transition).
p = k / "kernel_hal.c"
s = p.read_text()
if "web_spin_ms" not in s:
    a = "static void irql_transition(KIRQL from, KIRQL to)\n{"
    assert s.count(a) == 1
    s = s.replace(a, SPIN + a, 1)
    b = ("            int gil = xbox_gil_suspend();\n"
         "            EnterCriticalSection(&g_dispatch_lock);\n")
    assert s.count(b) == 1, s.count(b)
    s = s.replace(b, ("            int gil = xbox_gil_suspend();\n"
                      "#if defined(__EMSCRIPTEN__)\n"
                      "            {   /* spin a little before sleeping */\n"
                      "                double until = emscripten_get_now() + web_spin_ms();\n"
                      "                int got = 0;\n"
                      "                while (!(got = TryEnterCriticalSection(&g_dispatch_lock))\n"
                      "                       && emscripten_get_now() < until) { }\n"
                      "                if (!got)\n"
                      "                    EnterCriticalSection(&g_dispatch_lock);\n"
                      "            }\n"
                      "#else\n"
                      "            EnterCriticalSection(&g_dispatch_lock);\n"
                      "#endif\n"), 1)
    p.write_text(s)
    print("ok dispatch")
else:
    print("already dispatch")

"""tools_fix_dispatch_handoff.py: a thread lowering IRQL hands the dispatch lock to a thread waiting
for it (idempotent; edits ~/mc3-web/xboxrecomp/src/kernel/kernel_hal.c; run in WSL with python3).

The San Diego load's long stall (2026-11-12, "glitchy sound"; 16 s to minutes, then it recovers):
the main thread spins in the sound engine's "stop every sound of this owner, wait until they
are gone" (sub_003D840C), raising and lowering IRQL ~7,000 times a second. Every raise takes the
dispatch lock (irql_transition). The timer thread -- the one that runs the APU's and the GPU's
interrupt routines and their DPCs, i.e. what marks the voices stopped -- needs that lock too, and
a mutex is not fair: the main thread released it and took it straight back before the waiter
woke. The timer ran at ~170 calls/s instead of ~740, so the voices took ages to stop.
On the console an interrupt pre-empts DISPATCH code and lowering IRQL runs pending DPCs at once,
so this cannot happen there.
Now a contended raise counts itself as a waiter, and a lower that releases the lock while
someone waits holds back (at most 2 ms) until that waiter has taken it. Nothing changes when no
one is waiting.
"""
import os, sys

p = os.path.expanduser('~/mc3-web/xboxrecomp/src/kernel/kernel_hal.c')
t = open(p).read()
if 'g_dispatch_waiters' in t:
    print('already applied'); sys.exit(0)

def rep(a, b):
    global t
    assert t.count(a) == 1, (a[:70], t.count(a))
    t = t.replace(a, b)

rep("""static CRITICAL_SECTION g_dispatch_lock;
""", """static CRITICAL_SECTION g_dispatch_lock;
/* Threads blocked waiting for the dispatch lock, and how many times it has been taken: a lower
 * that releases it while someone waits holds back until a waiter has taken it
 * (tools_fix_dispatch_handoff.py). */
static volatile LONG g_dispatch_waiters, g_dispatch_takes;
""")

# the contended raise: count as a waiter while blocked (both the web spin and the plain path)
rep("""        if (!TryEnterCriticalSection(&g_dispatch_lock)) {
            int gil = xbox_gil_suspend();""", """        if (!TryEnterCriticalSection(&g_dispatch_lock)) {
            int gil = xbox_gil_suspend();
            InterlockedIncrement(&g_dispatch_waiters);""")
rep("""#else
            EnterCriticalSection(&g_dispatch_lock);
#endif
            xbox_gil_resume(gil);
        }
        t_dispatch_held = 1;""", """#else
            EnterCriticalSection(&g_dispatch_lock);
#endif
            InterlockedDecrement(&g_dispatch_waiters);
            xbox_gil_resume(gil);
        }
        InterlockedIncrement(&g_dispatch_takes);
        t_dispatch_held = 1;""")

# the lower: hand over to a waiter
rep("""        xbox_kernel_busy(-1);
        t_dispatch_held = 0;
        LeaveCriticalSection(&g_dispatch_lock);
    }""", """        LONG takes = g_dispatch_takes;
        xbox_kernel_busy(-1);
        t_dispatch_held = 0;
        LeaveCriticalSection(&g_dispatch_lock);
        if (g_dispatch_waiters > 0) {
            /* someone is blocked on the lock: let them have it before this thread can raise
             * again (a mutex hands it back to whoever asks first, which was always us) */
            ULONGLONG give_up = GetTickCount64() + 2;
            while (g_dispatch_waiters > 0 && g_dispatch_takes == takes
                   && GetTickCount64() <= give_up)
                SwitchToThread();
        }
    }""")
open(p, 'w').write(t)
print('applied')

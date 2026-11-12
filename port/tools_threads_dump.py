"""tools_threads_dump.py: per-thread "what is it doing" for a frozen game (idempotent).

Edits ~/mc3-web/xboxrecomp/src/kernel/kernel_bridge.c (run in WSL with python3):
every kernel call notes, in a small table keyed by host thread, the ordinal it is in,
the guest return address and its first argument; xbox_threads_dump() prints that
table and the guest lock's holder. The page calls it (Module._web_threads_dump) when
the game stops drawing, so a freeze's report says which thread waits on what.
"""
import os, sys

p = os.path.expanduser('~/mc3-web/xboxrecomp/src/kernel/kernel_bridge.c')
t = open(p).read()

def rep(a, b):
    global t
    assert t.count(a) == 1, (a[:60], t.count(a))
    t = t.replace(a, b)

def stack_step():
    """Step 2 (2026-11-11): each row also points at its thread's g_esp / g_ebp (TLS, but in
    the one shared memory), and the dump walks that thread's guest stack: the ebp chain and
    the code addresses near esp. A freeze caught with step 1 showed the guest lock's holder
    (the timer thread) running guest code forever; this says where."""
    global t
    if 'esp_p' in t:
        return
    rep("""static struct { volatile DWORD tid; volatile uint32_t ord, last, ret, arg0, n; }
    s_kcall[KCALL_MAX];""", """static struct { volatile DWORD tid; volatile uint32_t ord, last, ret, arg0, n;
                volatile uint32_t *esp_p, *ebp_p; }
    s_kcall[KCALL_MAX];""")
    rep("""                                           (LONG)tid, 0) == 0) {
                t_kcall = i;
                break;""", """                                           (LONG)tid, 0) == 0) {
                t_kcall = i;
                s_kcall[i].esp_p = &g_esp;
                s_kcall[i].ebp_p = &g_ebp;
                break;""")
    rep("""    fprintf(stderr, "[THREADS] %d threads\\n", n);""", """    /* each thread's guest stack: reads only inside the mapped 64 MB, so a stale
     * pointer cannot fault */
    for (i = 0; i < KCALL_MAX; i++) {
        uint32_t esp, ebp, k, m, line_n = 0;
        char line[400];
        if (!s_kcall[i].tid || !s_kcall[i].esp_p)
            continue;
        esp = *s_kcall[i].esp_p;
        ebp = *s_kcall[i].ebp_p;
        line_n = snprintf(line, sizeof line, "esp %08X ebp %08X | frames:", esp, ebp);
        for (k = 0; k < 12 && ebp >= 0x10000 && ebp < 0x3FFFFF8 && line_n < sizeof line - 12; k++) {
            uint32_t r = BRIDGE_MEM32(ebp + 4), nx = BRIDGE_MEM32(ebp);
            line_n += snprintf(line + line_n, sizeof line - line_n, " %08X", r);
            if (nx <= ebp) break;
            ebp = nx;
        }
        line_n += snprintf(line + line_n, sizeof line - line_n, " | near esp:");
        for (k = 0, m = 0; k < 64 && m < 14 && esp >= 0x10000 && esp + k * 4 < 0x3FFFFFC
                           && line_n < sizeof line - 12; k++) {
            uint32_t v = BRIDGE_MEM32(esp + k * 4);
            if (v >= 0x11000 && v < 0x42A000) {
                line_n += snprintf(line + line_n, sizeof line - line_n, " %08X", v);
                m++;
            }
        }
        fprintf(stderr, "[THREADS] tid %u stack: %s\\n", (unsigned)s_kcall[i].tid, line);
    }
    fprintf(stderr, "[THREADS] %d threads\\n", n);""")
    print('stack step applied')

if 'xbox_threads_dump' in t:
    stack_step()
    open(p, 'w').write(t)
    print('already applied (step 1)'); sys.exit(0)

# 1. the table, next to the guest-thread table
rep("""static SRWLOCK s_guest_threads_lock = SRWLOCK_INIT;
""", """static SRWLOCK s_guest_threads_lock = SRWLOCK_INIT;

/* What each thread is doing, for xbox_threads_dump: the kernel call it is in
 * (0 = running guest code), the last one, the guest return address and first
 * argument. Written only by the thread itself; read racily by the dump. */
#define KCALL_MAX 96
static struct { volatile DWORD tid; volatile uint32_t ord, last, ret, arg0, n; }
    s_kcall[KCALL_MAX];
static RECOMP_TLS int t_kcall = -1;
static void kcall_note(uint32_t ord, uint32_t ret, uint32_t arg0)
{
    if (t_kcall < 0) {
        DWORD tid = GetCurrentThreadId();
        int i;
        for (i = 0; i < KCALL_MAX; i++)
            if (InterlockedCompareExchange((volatile LONG *)&s_kcall[i].tid,
                                           (LONG)tid, 0) == 0) {
                t_kcall = i;
                break;
            }
        if (t_kcall < 0)
            return;
    }
    if (ord) {
        s_kcall[t_kcall].ord = ord;
        s_kcall[t_kcall].last = ord;
        s_kcall[t_kcall].ret = ret;
        s_kcall[t_kcall].arg0 = arg0;
        s_kcall[t_kcall].n++;
    } else {
        s_kcall[t_kcall].ord = 0;
    }
}
static void kcall_forget(void)
{
    if (t_kcall >= 0) {
        s_kcall[t_kcall].ord = s_kcall[t_kcall].last = 0;
        s_kcall[t_kcall].tid = 0;
        t_kcall = -1;
    }
}
""")

# 2. a thread that ends gives its row back
rep("""static void guest_thread_forget(void)
{
    DWORD tid = GetCurrentThreadId();
    int i;
""", """static void guest_thread_forget(void)
{
    DWORD tid = GetCurrentThreadId();
    int i;
    kcall_forget();
""")

# 3. the dump, after the lock's own functions
rep("""/* Around a call out of guest code (a kernel call): let everyone else run. */
int xbox_gil_suspend(void)""", """/* Every thread's kernel call and the guest lock's holder, to stderr. */
void xbox_threads_dump(void)
{
    int i, n = 0;
    fprintf(stderr, "[THREADS] guest lock: holder tid %u (%s), serving %llu, next %llu\\n",
            (unsigned)s_gil_holder_tid,
            s_gil_holder_label ? s_gil_holder_label : "-",
            (unsigned long long)s_gil_serving, (unsigned long long)s_gil_next);
    for (i = 0; i < KCALL_MAX; i++) {
        DWORD tid = s_kcall[i].tid;
        if (!tid)
            continue;
        n++;
        if (s_kcall[i].ord)
            fprintf(stderr, "[THREADS] tid %u: IN ordinal %u from %08X arg0 %08X (%u calls)\\n",
                    (unsigned)tid, s_kcall[i].ord, s_kcall[i].ret, s_kcall[i].arg0,
                    s_kcall[i].n);
        else
            fprintf(stderr, "[THREADS] tid %u: guest code (last ordinal %u from %08X arg0 %08X, %u calls)\\n",
                    (unsigned)tid, s_kcall[i].last, s_kcall[i].ret, s_kcall[i].arg0,
                    s_kcall[i].n);
    }
    fprintf(stderr, "[THREADS] %d threads\\n", n);
    fflush(stderr);
}

/* Around a call out of guest code (a kernel call): let everyone else run. */
int xbox_gil_suspend(void)""")

# 4. every kernel call notes itself
rep("""static void kernel_thunk_dispatch_inner(void)
{
    if (kernel_call_keeps_gil(g_kernel_dispatch_slot)) {
        kernel_thunk_dispatch_body();
        return;
    }""", """static void kernel_thunk_dispatch_body_noted(void);
static void kernel_thunk_dispatch_inner(void)
{
    if (kernel_call_keeps_gil(g_kernel_dispatch_slot)) {
        kernel_thunk_dispatch_body_noted();
        return;
    }""")
t = t.replace("""        t_kernel_gil_kept = 1;
        kernel_thunk_dispatch_body();
        t_kernel_gil_kept = 0;""", """        t_kernel_gil_kept = 1;
        kernel_thunk_dispatch_body_noted();
        t_kernel_gil_kept = 0;""", 1)
rep("""    xbox_kernel_busy(1);
    kernel_thunk_dispatch_body();
    xbox_kernel_busy(-1);
    xbox_gil_resume(gil);
}
""", """    xbox_kernel_busy(1);
    kernel_thunk_dispatch_body_noted();
    xbox_kernel_busy(-1);
    xbox_gil_resume(gil);
}

static void kernel_thunk_dispatch_body_noted(void)
{
    int slot = g_kernel_dispatch_slot;
    uint32_t ord = (slot >= 0 && slot < XBOX_KERNEL_THUNK_TABLE_SIZE) ? g_slot_ordinals[slot] : 0;
    if (ord)
        kcall_note(ord, g_esp ? BRIDGE_MEM32(g_esp) : 0, g_esp ? BRIDGE_MEM32(g_esp + 4) : 0);
    kernel_thunk_dispatch_body();
    if (ord)
        kcall_note(0, 0, 0);
}
""")
assert t.count('kernel_thunk_dispatch_body_noted();') == 3, t.count('kernel_thunk_dispatch_body_noted();')
stack_step()
open(p, 'w').write(t)
print('applied')

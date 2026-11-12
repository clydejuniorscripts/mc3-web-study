"""tools_gpu_dump.py: the [FREEZE] thread dump also says what the GPU executor is doing
(idempotent; edits ~/mc3-web/xboxrecomp/src/kernel/{nv2a_pb_exec.c,kernel_bridge.c}; WSL python3).

The free-roam freeze of 2026-11-12 (visit krouba8y): guest lock free, timer thread idle, and the
main thread waiting forever in KeWaitForSingleObject on D3D's push-buffer-space event
(device+0x1DCC, from sub_003DF4D0's loop at 0x3DF624) while drawing the HUD minimap's arrows --
so the GPU executor had stopped consuming the push buffer. The one executor wait with no limit
is the NOP-trap hand-off (trap_deliver_hooked: GPU interrupt raised, PGRAPH held until the
driver takes the trap). Its own "still pending after 2 s" line never reached the boot report.
Now the dump prints, as [THREADS] gpu: whether a trap is pending (which NOP, for how long),
PMC_INTR/EN, PGRAPH_INTR/EN, NSOURCE, and the executor's draw and flip counts.
"""
import os, sys

kd = os.path.expanduser('~/mc3-web/xboxrecomp/src/kernel/')
p1, p2 = kd + 'nv2a_pb_exec.c', kd + 'kernel_bridge.c'
t1, t2 = open(p1).read(), open(p2).read()

def rep(t, a, b, n=1):
    assert t.count(a) == n, (a[:70], t.count(a))
    return t.replace(a, b)

def dpc_step():
    """Step 2: the DPC queue too -- head/tail, each entry, and the vblank DPC (D3D's GPU-interrupt
    DPC, 0x3EE79C in MC3) with its Inserted flag: a DPC marked inserted but not in the queue
    would be refused forever, and D3D's push-buffer event never set again."""
    global t2
    if 'dpc queue' in t2:
        return
    t2 = rep(t2, """    {   /* and the GPU executor (tools_gpu_dump.py) */""", """    {   /* the DPC queue (tools_gpu_dump.py step 2) */
        extern void xbox_dpc_dump(void);
        xbox_dpc_dump();
    }
    {   /* and the GPU executor (tools_gpu_dump.py) */""")
    t2 = rep(t2, """static void bridge_KeRemoveQueueDpc(void)
{
    uint32_t dpc = STACK_ARG(0);""", """/* For the [FREEZE] dump: what is queued, and the vblank DPC's Inserted flag. */
void xbox_dpc_dump(void)
{
    LONG i, n = 0;
    char line[300];
    int len = snprintf(line, sizeof line, "[THREADS] dpc queue: head %ld tail %ld |",
                       (long)g_dpc_head, (long)g_dpc_tail);
    for (i = g_dpc_head; i != g_dpc_tail && n < 8 && len < (int)sizeof line - 24;
         i = (i + 1) % XBOX_MAX_PENDING_DPC, n++)
        len += snprintf(line + len, sizeof line - len, " %08X", g_dpc_queue[i].dpc);
    if (g_vblank_dpc)
        len += snprintf(line + len, sizeof line - len, " | vblank dpc %08X inserted %u routine %08X",
                        g_vblank_dpc, (unsigned)KDPC_INSERTED(g_vblank_dpc),
                        BRIDGE_MEM32(g_vblank_dpc + 12));
    fprintf(stderr, "%s\\n", line);
}

static void bridge_KeRemoveQueueDpc(void)
{
    uint32_t dpc = STACK_ARG(0);""")
    print('dpc step applied')

def apu_step():
    """Step 3: the APU too -- FECTL (trapped?), ISTS, IEN, and the raised interrupt lines. The
    San Diego load's sound wait spins while DirectSound reports the APU front end trapped
    (2026-11-12); this says whether its interrupt is raised, masked or never serviced."""
    global t2
    pq = os.path.expanduser('~/mc3-web/xboxrecomp/src/apu/apu_query.c')
    tq = open(pq).read()
    if 'mcpx_apu_dump' not in tq:
        tq += """
/* For the [FREEZE] thread dump (tools_gpu_dump.py step 3). */
extern uint32_t xbox_irq_lines(void);
void mcpx_apu_dump(void)
{
    if (!g_state)
        return;
    fprintf(stderr, "[THREADS] apu: FECTL %08X%s ISTS %08X IEN %08X, irq lines %08X\\n",
            g_state->regs[NV_PAPU_FECTL], mcpx_apu_fe_trapped() ? " (TRAPPED/HALTED)" : "",
            g_state->regs[NV_PAPU_ISTS], g_state->regs[NV_PAPU_IEN], xbox_irq_lines());
}
"""
        if '#include <stdio.h>' not in tq:
            tq = '#include <stdio.h>\n' + tq
        open(pq, 'w').write(tq)
    if 'mcpx_apu_dump' not in t2:
        t2 = rep(t2, """    {   /* and the GPU executor (tools_gpu_dump.py) */""", """    {   /* the APU (tools_gpu_dump.py step 3) */
        extern void mcpx_apu_dump(void) __attribute__((weak));
        if (mcpx_apu_dump) mcpx_apu_dump();
    }
    {   /* and the GPU executor (tools_gpu_dump.py) */""")
    print('apu step applied')

if 'nv2a_pb_exec_dump' in t1:
    dpc_step()
    apu_step()
    open(p2, 'w').write(t2)
    print('already applied (step 1)'); sys.exit(0)

t1 = rep(t1, """static void trap_deliver_hooked(volatile uint32_t *nv, uint32_t method,
                                uint32_t subch, uint32_t param)
{""", """/* For the freeze dump (tools_gpu_dump.py): a trap waiting for the driver, since when. */
static volatile LONG s_trap_waiting;
static volatile uint32_t s_trap_wait_param;
static volatile ULONGLONG s_trap_wait_since;

static void trap_deliver_hooked(volatile uint32_t *nv, uint32_t method,
                                uint32_t subch, uint32_t param)
{""")
t1 = rep(t1, """    xbox_set_irq_line(3, 1);
    /* PGRAPH stalls until the driver has taken the trap, however long. */""",
"""    xbox_set_irq_line(3, 1);
    s_trap_wait_param = param; s_trap_wait_since = GetTickCount64();
    InterlockedExchange(&s_trap_waiting, 1);
    /* PGRAPH stalls until the driver has taken the trap, however long. */""")
t1 = rep(t1, """    xbox_set_irq_line(3, 0);
    if ((++handled_n & 1023) == 0)""", """    InterlockedExchange(&s_trap_waiting, 0);
    xbox_set_irq_line(3, 0);
    if ((++handled_n & 1023) == 0)""")
t1 = rep(t1, """void nv2a_pb_flip_retired(unsigned n)
{""", """/* The executor's state, for the [FREEZE] thread dump (kernel_bridge.c xbox_threads_dump). */
void nv2a_pb_exec_dump(void)
{
    volatile uint32_t *nv = (volatile uint32_t *)
        ((uint8_t *)xbox_GetMemoryOffset() + 0xFD000000u);
    LONG w = s_trap_waiting;
    fprintf(stderr, "[THREADS] gpu: trap %s", w ? "PENDING" : "none");
    if (w)
        fprintf(stderr, " (NOP %u for %llu ms)", s_trap_wait_param,
                (unsigned long long)(GetTickCount64() - s_trap_wait_since));
    fprintf(stderr, ", PMC_INTR %08X EN %08X, PGRAPH_INTR %08X EN %08X, NSOURCE %08X,"
            " draws %u, flips %u (read %u write %u), busy %d%%\\n",
            nv[0x100 / 4], nv[0x140 / 4], nv[0x400100 / 4], nv[0x400140 / 4],
            nv[0x400108 / 4], s_gpu.draws, s_gpu.flips, s_gpu.flip_read, s_gpu.flip_write,
            nv2a_exec_busy_percent());
    fflush(stderr);
}

void nv2a_pb_flip_retired(unsigned n)
{""")
if 'int nv2a_exec_busy_percent(void);' not in t1:
    t1 = rep(t1, "/* For the freeze dump (tools_gpu_dump.py)", "int nv2a_exec_busy_percent(void);\n/* For the freeze dump (tools_gpu_dump.py)")
t2 = rep(t2, """    fprintf(stderr, "[THREADS] %d threads\\n", n);""", """    {   /* and the GPU executor (tools_gpu_dump.py) */
        extern void nv2a_pb_exec_dump(void) __attribute__((weak));
        if (nv2a_pb_exec_dump) nv2a_pb_exec_dump();
    }
    fprintf(stderr, "[THREADS] %d threads\\n", n);""")
dpc_step()
apu_step()
open(p1, 'w').write(t1); open(p2, 'w').write(t2)
print('applied')

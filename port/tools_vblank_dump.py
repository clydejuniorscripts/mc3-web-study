"""tools_vblank_dump.py: the [FREEZE] thread dump also says what the vblank interrupt is doing
(idempotent; edits ~/mc3-web/xboxrecomp/src/kernel/kernel_bridge.c; WSL python3).

The garage-load freeze of 2026-11-12 (live 6af5c551, 13:30): the main thread waits in the
loading-screen loop, the guest lock is free, the DPC queue is empty and D3D's vblank DPC
(0x3EE79C) is not inserted -- so no vblank reaches D3D, and the loop waits for good. The tick
(kernel_vblank_tick) still runs; either the NV2A interrupt is not connected, or D3D's ISR declines
it (vblank masked, a DPC it thinks is pending), or it claims it without queueing the DPC. Now the
dump's dpc line says, since the last time a vblank DPC ran: ticks, how many raised the ISR, and
claimed / declined / not callable / dropped counts, plus PCRTC_INTR_0 / INTR_EN_0 and how long ago
the vblank DPC last ran.
"""
import os, sys
p = os.path.expanduser('~/mc3-web/xboxrecomp/src/kernel/kernel_bridge.c')
t = open(p).read()
if 'tools_vblank_dump' in t:
    print('already applied'); sys.exit(0)

def rep(a, b):
    global t
    assert t.count(a) == 1, (a[:60], t.count(a))
    t = t.replace(a, b)

# counters, declared before the first use (xbox_dpc_dump sits above kernel_vblank_tick)
rep("""static uint32_t g_vblank_dpc;""", """static uint32_t g_vblank_dpc;
/* vblank delivery since the vblank DPC last ran, for the [FREEZE] dump (tools_vblank_dump.py) */
static volatile LONG s_vbd_ticks, s_vbd_raised, s_vbd_claimed, s_vbd_declined, s_vbd_nocall,
                     s_vbd_dropped, s_vbd_noconn;
static volatile ULONGLONG s_vbd_last_run_ms;""")
# the vblank DPC ran: reset (the line right after the "is it the vblank DPC" test)
rep("""    if (dpc_va == g_vblank_dpc)""", """    if (dpc_va == g_vblank_dpc) {   /* tools_vblank_dump.py */
        s_vbd_ticks = s_vbd_raised = s_vbd_claimed = s_vbd_declined = 0;
        s_vbd_nocall = s_vbd_dropped = s_vbd_noconn = 0;
        s_vbd_last_run_ms = GetTickCount64();
    }
    if (dpc_va == g_vblank_dpc)""")
rep("""    InterlockedIncrement(&s_vb_count);

    if (!xbox_GetConnectedInterrupt(NV2A_VECTOR))
        return;
""", """    InterlockedIncrement(&s_vb_count);
    InterlockedIncrement(&s_vbd_ticks);

    if (!xbox_GetConnectedInterrupt(NV2A_VECTOR)) {
        InterlockedIncrement(&s_vbd_noconn);
        return;
    }
    InterlockedIncrement(&s_vbd_raised);
""")
rep("""        if (claimed < 0 || !queued)
            xbox_Nv2aVblankDrop();""", """        InterlockedIncrement(claimed < 0 ? &s_vbd_nocall : claimed ? &s_vbd_claimed : &s_vbd_declined);
        if (claimed < 0 || !queued) {
            InterlockedIncrement(&s_vbd_dropped);
            xbox_Nv2aVblankDrop();
        }""")
rep("""    fprintf(stderr, "%s\\n", line);
}

static void bridge_KeRemoveQueueDpc(void)""", """    fprintf(stderr, "%s\\n", line);
    fprintf(stderr, "[THREADS] vblank: since its DPC last ran (%llu ms ago): %ld ticks, %ld not connected,"
            " %ld raised: %ld claimed, %ld declined, %ld not callable, %ld dropped |"
            " PCRTC_INTR %08X EN %08X\\n",
            s_vbd_last_run_ms ? (unsigned long long)(GetTickCount64() - s_vbd_last_run_ms) : 0ull,
            (long)s_vbd_ticks, (long)s_vbd_noconn, (long)s_vbd_raised, (long)s_vbd_claimed,
            (long)s_vbd_declined, (long)s_vbd_nocall, (long)s_vbd_dropped,
            BRIDGE_MEM32(0xFD000000u + 0x600100u), BRIDGE_MEM32(0xFD000000u + 0x600140u));
}

static void bridge_KeRemoveQueueDpc(void)""")
open(p, 'w').write(t)
print('applied')

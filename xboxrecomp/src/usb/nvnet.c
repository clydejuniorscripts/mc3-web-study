/* nvnet.c — nForce (NvNet) NIC model for the web build, bridging the title's
 * System Link traffic to the relay (the web_net rings in web_host.c).
 *
 * The title runs a full forcedeth-style driver (sub_0039DEB0..sub_0039E7B3 in
 * the lift) that drives the NIC by MMIO at 0xFEF00000. On the web build that
 * aperture is plain RAM — wasm has no MMIO fault trap — so this polls it, the
 * way the NV2A busy-bit thread does, instead of trapping register writes:
 *   - it reads the ring base/size the driver programs (regs 0x100/0x104/0x108),
 *   - reports the link up (so the driver's init proceeds),
 *   - scans the TX descriptor ring for frames the driver queued and forwards
 *     them to the relay,
 *   - raises the NIC interrupt (the ohci.c pattern: call the title's connected
 *     ISR on a worker stack) so the driver reaps its TX ring.
 *
 * Increment 1: init + TX capture + TX-done interrupt. RX injection and the
 * receive interrupt are the next step. Enabled when RECOMP_NET_LINK=1.
 */
#include "../kernel/xbox_memory_layout.h"
#include "../kernel/kernel.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <unistd.h>

#if defined(__EMSCRIPTEN__)   /* the relay bridge (web_net) is web-only */
#include <emscripten/heap.h>
#include <emscripten.h>

typedef void (*recomp_func_t)(void);
extern ptrdiff_t xbox_GetMemoryOffset(void);
extern recomp_func_t recomp_lookup(uint32_t xbox_va);
void xbox_gil_isr_begin(void);
void xbox_gil_isr_end(void);
extern int  xbox_worker_stack_alloc(void);
extern void xbox_worker_stack_free(int slot);
extern uint32_t xbox_GetConnectedInterrupt(uint32_t vector);
/* Captured at connect time via BRIDGE_MEM32 — correct for KSEG guest VAs. */
extern uint32_t xbox_GetConnectedRoutine(uint32_t vector);
extern uint32_t xbox_GetConnectedContext(uint32_t vector);
extern uint32_t xbox_FindConnectedVector(uint32_t lo, uint32_t hi);

/* The relay rings (web_host.c). TX = frames to send to the relay. */
extern int web_net_tx_push(const uint8_t *p, int n);
extern int web_net_rx_pop(uint8_t *out, int cap);   /* for the RX step, next */

/* The recomp CPU-state globals (RECOMP_TLS from xbox_memory_layout.h), driven
 * to call the ISR exactly as ohci.c does. */
extern RECOMP_TLS uint32_t g_eax, g_ecx, g_edx, g_esp;
extern RECOMP_TLS uint32_t g_ebx, g_esi, g_edi;

/* ── Play Online: spawn into the driving world ─────────────────────────────
 * Captured (PLAY_ONLINE.md): mcGameState::EnterState(2) on the singleton at
 * guest VA 0x80D95910 enters the in-world driving state (4 = front-end). This
 * calls that lifted function (sub_00021A70, thiscall) the proven ohci/nic way:
 * a guest worker stack, `this` in ECX, the state arg on the stack, under the
 * guest lock. The Play Online menu item will call this; for now it is exported
 * so the page can trigger it to validate the launch.
 *
 * NOTE: EnterState(2) needs an owned car and a loaded city/profile context
 * (the capture reached it after the garage with that context set up). From a
 * bare menu it may need the mcConfig city/mode set first — this export is the
 * test that tells us. */
#define MC_GAMESTATE_VA  0x80D95910u
#define MC_STATE_WORLD   2u
#define SUB_ENTERSTATE   0x00021A70u

EMSCRIPTEN_KEEPALIVE int web_play_online(void)
{
    recomp_func_t fn = recomp_lookup(SUB_ENTERSTATE);
    uint8_t *mem;
    int slot;
    if (!fn) { fprintf(stderr, "  [PLAY] EnterState (0x%08X) not found\n", SUB_ENTERSTATE); return -1; }
    slot = xbox_worker_stack_alloc();
    if (slot < 0) { fprintf(stderr, "  [PLAY] no worker stack\n"); return -1; }
    mem = (uint8_t *)xbox_GetMemoryOffset();
    g_esp = XBOX_WORKER_STACK_TOP(slot);
    g_eax = g_ecx = g_edx = g_ebx = g_esi = g_edi = 0;
    g_ecx = MC_GAMESTATE_VA;                                   /* this (thiscall) */
    g_esp -= 4; *(uint32_t *)(mem + g_esp) = MC_STATE_WORLD;   /* arg: state 2    */
    g_esp -= 4; *(uint32_t *)(mem + g_esp) = 0xDEADBEEFu;      /* return address  */
    fprintf(stderr, "  [PLAY] EnterState(2) on mcGameState 0x%08X\n", MC_GAMESTATE_VA);
    fflush(stderr);
    xbox_gil_isr_begin();
    fn();
    xbox_gil_isr_end();
    xbox_worker_stack_free(slot);
    fprintf(stderr, "  [PLAY] EnterState returned\n"); fflush(stderr);
    return 0;
}

/* The current game mode (mcConfig, global 0x507B14): 0=cruise, 1=arcade,
 * 2=adventure(career), 3=frontend(menus), 4=raceeditor, 5=garage. The page's
 * Play Online automation polls this to know when it has reached free-roam
 * (mode 0) after driving the game's own Arcade->Cruise->START flow. */
#define MC_MODE_GLOBAL   0x507B14u
EMSCRIPTEN_KEEPALIVE int web_game_mode(void)
{
    uint8_t *mem = (uint8_t *)xbox_GetMemoryOffset();
    return (int)(*(volatile uint32_t *)(mem + MC_MODE_GLOBAL));
}

/* The wasm-linear-memory byte offset of guest VA 0 (xbox_GetMemoryOffset).
 * Guest memory is laid out at its raw VA (incl. KSEG) in the 4 GB wasm memory,
 * so the page can read any guest address directly:
 *   base = Module._web_mem_base();
 *   u32  = new Uint32Array(wasmMemory.buffer);  f32 = new Float32Array(...);
 *   peek32(va) = u32[(base+va)>>>2];  peekF(va) = f32[(base+va)>>>2];
 * Used to find the local car's transform (for ghosts) by exploring the world
 * session object at 0x80D958B0 while driving. */
EMSCRIPTEN_KEEPALIVE uint32_t web_mem_base(void)
{
    return (uint32_t)(uintptr_t)xbox_GetMemoryOffset();
}

/* ── NvNet registers (offsets from 0xFEF00000) ─────────────────────────── */
#define NIC_BASE        0xFEF00000u      /* flat: host = xbox_GetMemoryOffset() + VA */
#define R_IRQSTATUS     0x000
#define R_IRQMASK       0x004
#define R_TXSTATUS      0x088
#define R_RXSTATUS      0x098
#define R_TXRING        0x100
#define R_RXRING        0x104
#define R_RINGSIZES     0x108
#define R_LINKSPEED     0x110
#define R_MIISTATUS     0x180
/* IRQ status bits (forcedeth). */
#define IRQ_RX          0x0002
#define IRQ_TX_OK       0x0010
#define IRQ_LINK        0x0040
/* Descriptor flags (8-byte v1 desc: u32 buffer; u16 length; u16 flags). */
#define DESC_VALID      0x8000u          /* NIC-owned: TX to send / RX free */

#define NIC_DESC_MAX    1024
#define NIC_FRAME_MAX   1600

static volatile int s_nic_on;
static uint32_t s_nic_vector = 0xFFFFFFFFu;   /* discovered from the driver's ISR */
static uint8_t *s_mem;                         /* flat base: xbox_GetMemoryOffset() */

static inline volatile uint32_t *reg(uint32_t off)
{ return (volatile uint32_t *)(s_mem + NIC_BASE + off); }

/* wasm linear memory grows on demand; the high aperture is unreachable until
 * it has grown to cover it (a raw read there traps otherwise). */
static int mem_covers(uintptr_t top)
{
    size_t bytes = emscripten_get_heap_size();
    static size_t last;
    if (bytes != last) {
        fprintf(stderr, "  [NIC] heap %zu MB, need addr 0x%08X\n",
                bytes / (1024 * 1024), (unsigned)((uintptr_t)s_mem + top));
        fflush(stderr); last = bytes;
    }
    return (uintptr_t)s_mem + top < bytes;
}

/* A ring/buffer bus address the driver programmed -> a host pointer in main
 * RAM, or NULL if it does not look like a low physical address. Contiguous
 * memory is identity-mapped; KSEG bases (0x80000000/0xA0000000) map to phys. */
static uint8_t *dma(uint32_t bus)
{
    uint32_t pa = bus & 0x0FFFFFFFu;         /* strip a KSEG base if present */
    if (!pa || pa >= 0x08000000u) return NULL;
    return s_mem + pa;
}

/* The NIC driver lives at 0x0039DEB0..0x0039F000 in the lift; its ISR is
 * sub_0039DF4B. Match on this range to find the vector it connected on. */
#define NIC_ISR_LO      0x0039DE00u
#define NIC_ISR_HI      0x0039F000u

/* Find the vector the title connected its NIC ISR on. The kernel captured each
 * ISR's routine at connect time (BRIDGE_MEM32, correct for KSEG), so this asks
 * it by routine range rather than re-reading guest memory from this thread. */
static void nic_find_vector(void)
{
    uint32_t v = xbox_FindConnectedVector(NIC_ISR_LO, NIC_ISR_HI);
    if (v != 0xFFFFFFFFu && s_nic_vector != v) {
        s_nic_vector = v;
        fprintf(stderr, "  [NIC] ISR on vector %u -> routine 0x%08X\n",
                v, xbox_GetConnectedRoutine(v));
        fflush(stderr);
    }
}

/* Call the title's NIC ISR on this thread, with a guest stack (ohci.c pattern).
 * BOOLEAN ServiceRoutine(PKINTERRUPT, PVOID context), __stdcall. */
static int nic_call_isr(void)
{
    uint32_t kint, routine, context;
    recomp_func_t fn;
    int slot;
    if (s_nic_vector == 0xFFFFFFFFu) return -1;
    kint = xbox_GetConnectedInterrupt(s_nic_vector);   /* guest VA, passed as arg 1 */
    if (!kint) return -1;
    routine = xbox_GetConnectedRoutine(s_nic_vector);  /* captured at connect time */
    context = xbox_GetConnectedContext(s_nic_vector);
    if (!routine) return -1;
    fn = recomp_lookup(routine);
    if (!fn) return -1;
    slot = xbox_worker_stack_alloc();
    if (slot < 0) return -1;
    g_esp = XBOX_WORKER_STACK_TOP(slot);
    g_eax = g_ecx = g_edx = g_ebx = g_esi = g_edi = 0;
    g_esp -= 4; *(uint32_t *)(s_mem + g_esp) = context;   /* arg 2 */
    g_esp -= 4; *(uint32_t *)(s_mem + g_esp) = kint;      /* arg 1 */
    g_esp -= 4; *(uint32_t *)(s_mem + g_esp) = 0xDEADBEEFu;
    xbox_gil_isr_begin();
    fn();
    xbox_gil_isr_end();
    xbox_worker_stack_free(slot);
    return (int)(g_eax & 1u);
}

/* Scan the TX ring for descriptors the driver marked VALID, forward each
 * frame to the relay, and mark it done. Returns how many were sent. */
static int nic_tx_scan(void)
{
    uint32_t txring = *reg(R_TXRING);
    uint32_t sizes  = *reg(R_RINGSIZES);
    uint32_t txcount = (sizes & 0xFFFF) + 1;
    int sent = 0;
    uint8_t *ring = dma(txring);
    if (!ring || txcount == 0 || txcount > NIC_DESC_MAX) return 0;
    for (uint32_t i = 0; i < txcount; i++) {
        uint8_t *d = ring + i * 8;
        uint16_t flags = *(uint16_t *)(d + 6);
        if (!(flags & DESC_VALID)) continue;
        uint32_t buf = *(uint32_t *)(d + 0);
        uint16_t len = *(uint16_t *)(d + 4);
        uint8_t *fp = dma(buf);
        if (len && len <= NIC_FRAME_MAX && fp) {
            web_net_tx_push(fp, len);
            static int logged;
            if (logged < 8) {
                const uint8_t *f = fp;
                fprintf(stderr, "  [NIC] TX %u bytes  dst %02x:%02x:%02x:%02x:%02x:%02x"
                                " src %02x:%02x:%02x:%02x:%02x:%02x type %02x%02x\n",
                        len, f[0],f[1],f[2],f[3],f[4],f[5], f[6],f[7],f[8],f[9],f[10],f[11],
                        f[12], f[13]);
                fflush(stderr); logged++;
            }
        }
        *(uint16_t *)(d + 6) = flags & ~DESC_VALID;   /* done: hand back to the driver */
        sent++;
    }
    return sent;
}

static void *nic_thread(void *arg)
{
    uint32_t last_tx = 0, last_rx = 0;
    int waited = 0;
    (void)arg;
    s_mem = (uint8_t *)xbox_GetMemoryOffset();
    fprintf(stderr, "  [NIC] model up (polling 0x%08X); waiting for the driver\n", NIC_BASE);
    fflush(stderr);
    for (;;) {
        /* Hold off until the aperture is mapped (memory grown that far). */
        if (!mem_covers(NIC_BASE + 0x1000)) {
            if (!waited) { fprintf(stderr, "  [NIC] waiting for memory to reach the aperture\n"); fflush(stderr); waited = 1; }
            usleep(5000);
            continue;
        }
        /* Heartbeat + what interrupts are connected (diagnostic). */
        static uint32_t iters;
        if ((++iters % 3000u) == 0u) {
            char b[160]; int k = 0;
            for (uint32_t v = 0; v < 32 && k < 130; v++) {
                if (xbox_GetConnectedInterrupt(v))
                    k += snprintf(b + k, sizeof b - k, "%u:%08X ", v, xbox_GetConnectedRoutine(v));
            }
            fprintf(stderr, "  [NIC] alive iter %u vec %d; connected { %s}\n",
                    iters, (int)s_nic_vector, b);
            fflush(stderr);
        }

        /* Report the link up so the driver's setup completes and stays up. */
        *reg(R_MIISTATUS) |= 0x04;             /* link-up bit (forcedeth MIISTAT) */
        *reg(R_LINKSPEED) = 0x10;              /* 100 Mbit, full duplex marker */

        if (s_nic_vector == 0xFFFFFFFFu) nic_find_vector();

        uint32_t txring = *reg(R_TXRING), rxring = *reg(R_RXRING);
        if (txring != last_tx || rxring != last_rx) {
            fprintf(stderr, "  [NIC] rings programmed: TX 0x%08X RX 0x%08X sizes 0x%08X\n",
                    txring, rxring, *reg(R_RINGSIZES));
            fflush(stderr);
            last_tx = txring; last_rx = rxring;
        }

        int sent = nic_tx_scan();
        if (sent) {
            *reg(R_IRQSTATUS) |= IRQ_TX_OK;    /* TX complete */
            *reg(R_TXSTATUS)  |= 0x01;
            if (*reg(R_IRQMASK) & IRQ_TX_OK)
                nic_call_isr();                /* let the driver reap the ring */
        }
        usleep(1000);
    }
    return NULL;
}

/* Called from web_boot when RECOMP_NET_LINK=1. */
void xbox_nic_init(void)
{
    const char *e = getenv("RECOMP_NET_LINK");
    pthread_t th;
    if (!(e && e[0] == '1')) {
        fprintf(stderr, "  [NIC] off (set RECOMP_NET_LINK=1 for System Link)\n");
        return;
    }
    if (s_nic_on) return;
    s_nic_on = 1;
    if (pthread_create(&th, NULL, nic_thread, NULL) != 0)
        fprintf(stderr, "  [NIC] could not start the poll thread\n");
    else
        pthread_detach(th);
}

#else
void xbox_nic_init(void) { }   /* native reference build: no relay bridge */
#endif

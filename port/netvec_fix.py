#!/usr/bin/env python3
"""System Link NIC: record each connected ISR's routine/context at connect time
and expose a vector-by-routine-range lookup.

The NvNet model (nvnet.c) runs on its own poll thread and has to discover which
interrupt vector the title connected its NIC driver's ISR on. It did that by
re-reading the KINTERRUPT from guest memory with a raw host pointer; for the
NIC the kernel stores KSEG (0x80000000-based) KINTERRUPT VAs, which that raw
read resolves to the wrong (zero-filled) linear-memory page -> garbage, so the
vector was never found.

KeConnectInterrupt already reads the routine correctly via BRIDGE_MEM32 (it
prints it in its log line). So capture the routine and context there, once, on
the guest thread, into parallel tables, and let device models look the vector
up by the lifted address range of their driver's ISR -- no guest-memory read
from the device thread at all."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/kernel/kernel_bridge.c"
s = p.read_text()

if "xbox_FindConnectedVector" in s:
    print("already")
    raise SystemExit

# 1) Parallel tables beside g_connected_isr.
anchor = "static uint32_t g_connected_isr[XBOX_MAX_VECTORS];   /* KINTERRUPT guest VA */"
assert anchor in s, "g_connected_isr declaration not found"
tables = anchor + """
static uint32_t g_connected_routine[XBOX_MAX_VECTORS]; /* ISR routine guest VA  */
static uint32_t g_connected_context[XBOX_MAX_VECTORS]; /* its context argument  */"""
s = s.replace(anchor, tables, 1)

# 2) Record routine/context at connect time (BRIDGE_MEM32 is correct here).
rec_anchor = "            g_connected_isr[vector] = interrupt_va;\n"
assert rec_anchor in s, "connect-time store not found"
rec = rec_anchor + """            g_connected_routine[vector] = BRIDGE_MEM32(interrupt_va + 0);
            g_connected_context[vector] = BRIDGE_MEM32(interrupt_va + 4);
"""
s = s.replace(rec_anchor, rec, 1)

# 3) Helpers right after xbox_GetConnectedInterrupt.
helper_anchor = """uint32_t xbox_GetConnectedInterrupt(uint32_t vector)
{
    return (vector < XBOX_MAX_VECTORS) ? g_connected_isr[vector] : 0;
}"""
assert helper_anchor in s, "xbox_GetConnectedInterrupt body not found"
helpers = helper_anchor + """

/* The ISR routine / context a title connected on this vector, captured at
 * connect time via BRIDGE_MEM32 (correct for the KSEG guest VAs the kernel
 * stores). Device models on their own threads read these instead of
 * re-dereferencing the KINTERRUPT from guest memory. */
uint32_t xbox_GetConnectedRoutine(uint32_t vector)
{
    return (vector < XBOX_MAX_VECTORS) ? g_connected_routine[vector] : 0;
}
uint32_t xbox_GetConnectedContext(uint32_t vector)
{
    return (vector < XBOX_MAX_VECTORS) ? g_connected_context[vector] : 0;
}

/* The first connected vector whose ISR routine falls in [lo, hi), else
 * 0xFFFFFFFF. A device model finds its vector by the lifted address range of
 * its driver's ISR, with no guest-memory scan from the device thread. */
uint32_t xbox_FindConnectedVector(uint32_t lo, uint32_t hi)
{
    for (uint32_t v = 0; v < XBOX_MAX_VECTORS; v++) {
        uint32_t r = g_connected_routine[v];
        if (g_connected_isr[v] && r >= lo && r < hi)
            return v;
    }
    return 0xFFFFFFFFu;
}"""
s = s.replace(helper_anchor, helpers, 1)

p.write_text(s)
print("ok")

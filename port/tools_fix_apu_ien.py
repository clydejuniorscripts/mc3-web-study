"""tools_fix_apu_ien.py: writing the APU's interrupt-enable register re-evaluates the interrupt line
(idempotent; edits ~/mc3-web/xboxrecomp/src/apu/apu_core.c; run in WSL with python3).

The San Diego load's long stall ("glitchy sound", 2026-11-12): the sound engine stops a bank's
sounds and waits until they are gone (sub_003D840C). A voice stop is confirmed through the APU
front end; when the front end traps, the whole APU pipeline -- and its clock -- stops until
DirectSound's interrupt handler clears it. The trap raises the interrupt in update_irq, but only
while IEN allows it. DirectSound's ISR masks IEN and its DPC unmasks it; a trap that arrived in
between was never raised, because a write to IEN only stored the value (default case). The line
is (ISTS & IEN) on the hardware, so the pending trap should fire the moment IEN is written back.
Lost, the front end stayed trapped until some unrelated ISTS write re-checked the line: 16 s to
minutes with no voice stopping and no frames.
"""
import os, sys

p = os.path.expanduser('~/mc3-web/xboxrecomp/src/apu/apu_core.c')
t = open(p).read()
if 'tools_fix_apu_ien' in t:
    print('already applied'); sys.exit(0)

a = """    case NV_PAPU_FEMEMDATA:
        /* 'magic write' - value written to FEMEMADDR on notify completion */"""
b = """    case NV_PAPU_IEN:
        /* The line is (ISTS & IEN): unmasking with a trap pending raises it now. Storing the
         * value alone lost a trap that came while DirectSound's ISR had IEN masked, and the
         * front end stayed trapped -- APU time stopped, voices never finished stopping
         * (tools_fix_apu_ien.py). */
        qatomic_set(&d->regs[addr], (uint32_t)val);
        update_irq(d);
        qemu_cond_broadcast(&d->cond);
        break;
    case NV_PAPU_FEMEMDATA:
        /* 'magic write' - value written to FEMEMADDR on notify completion */"""
assert t.count(a) == 1, t.count(a)
t = t.replace(a, b)
open(p, 'w').write(t)
print('applied')

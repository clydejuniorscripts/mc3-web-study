"""tools_fix_ohci_lock.py: the emulated USB controller walks the transfer lists under the guest
lock (idempotent; edits ~/mc3-web/xboxrecomp/src/usb/ohci.c, run in WSL with python3).

The intermittent free-roam freeze (2026-11-11, caught twice with the [THREADS] dump): the
timer thread held the guest lock forever inside the game's USB driver, in sub_004103D4's walk
of one endpoint's TDs from HeadP to TailP (loc_00410452: td = base + td->NextTD until TailP).
The controller thread retired TDs on that same list WITHOUT the guest lock -- retiring rewrites
td->NextTD to point into the done queue -- so a driver walk that overlapped it followed a chain
that never reached TailP, and spun with the lock held: every other thread stopped. On hardware
the driver sets sKip and waits a frame before touching a list; here the two could interleave.

Now each list pass (periodic, bulk, control, done-list publish) runs with the guest lock held,
as the controller already does around the game's ISR: a driver edit made at DISPATCH level is
never seen half-done, and the controller never retires a TD in the middle of a driver walk.
"""
import os, sys

p = os.path.expanduser('~/mc3-web/xboxrecomp/src/usb/ohci.c')
t = open(p).read()
if 'OHCI_LIST_LOCK' in t:
    print('already applied'); sys.exit(0)

a = """        if (hc->reg[HcInterruptStatus / 4] & INTR_WDH)
            goto deliver;
"""
b = """        if (hc->reg[HcInterruptStatus / 4] & INTR_WDH)
            goto deliver;

        /* OHCI_LIST_LOCK: the lists are walked with the guest lock held, so they never change
         * under a driver walk at DISPATCH level, nor a driver edit under this walk
         * (tools_fix_ohci_lock.py: the timer thread spun forever in sub_004103D4 on a TD chain
         * this thread had half retired, holding the lock, and the game froze). */
        xbox_gil_isr_begin();
"""
assert t.count(a) == 1, t.count(a)
t = t.replace(a, b)

a2 = """        ohci_flush_done(hc);    /* publish TDs held while WDH was set */
    deliver:"""
b2 = """        ohci_flush_done(hc);    /* publish TDs held while WDH was set */
        xbox_gil_isr_end();     /* OHCI_LIST_LOCK */
    deliver:"""
assert t.count(a2) == 1, t.count(a2)
t = t.replace(a2, b2)
open(p, 'w').write(t)
print('applied')

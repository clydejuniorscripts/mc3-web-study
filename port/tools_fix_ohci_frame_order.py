"""tools_fix_ohci_frame_order.py: the emulated OHCI controller starts the next frame only after it
has finished with the lists (idempotent; edits ~/mc3-web/xboxrecomp/src/usb/ohci.c; WSL python3).

The USB freezes of 2026-11-11/12 (timer thread holding the guest lock forever in the XAPI USB
DPC): TD chains running into freed TDs (NextTD -1, the free list's mark), a "TD" at physical 0
on the done queue, request lists that loop -- corruption in three spots of one driver. The
controller thread, every tick and concurrently with guest code, did: frame number += 4 and
StartOfFrame (HccaFrameNumber, INTR_SF), THEN walk the periodic, bulk and control lists --
reading ED heads and TD links, writing TD info, NextTD (the done-queue link) and ED heads. A
driver taking TDs off an endpoint does what OHCI says: skip the ED, wait for the next frame,
then free them, since a new frame means the controller is done with the old lists. Here the new
frame came first and the walk after it, so the driver could free and reuse TDs the walk was
still writing into. Now the frame clock moves at the end of the tick, after any walk (and also
on a tick that walks nothing, so time keeps passing). First tried with the guest lock around
clock and walk (2026-11-12, 6af60d74): no USB freeze in 4 boots, but the page's menu walk failed
in 2 of them (a Start press landing on the main menu, into Career) -- pad reports waited for the
lock during loads. This ordering needs no lock.
"""
import os, sys
p = os.path.expanduser('~/mc3-web/xboxrecomp/src/usb/ohci.c')
t = open(p).read()
if 'tools_fix_ohci_frame_order' in t:
    print('already applied'); sys.exit(0)

def rep(a, b):
    global t
    assert t.count(a) == 1, (a[:70], t.count(a))
    t = t.replace(a, b)

# undo the lock version if it is there
if 'tools_fix_ohci_walk_lock' in t:
    rep("""        /* From the frame clock to the published done queue: under the guest lock, so a
         * driver that waits for the next frame before freeing TDs never frees one this
         * walk is still writing (tools_fix_ohci_walk_lock.py). */
        xbox_gil_isr_begin();
        walk_locked = 1;

""", "")
    rep("""        if (walk_locked) {
            walk_locked = 0;
            xbox_gil_isr_end();
        }
""", "")
    rep("""        int walk_locked = 0;
""", "")

# cut the frame-clock block out of its place before the walk ...
a = t.index("        /* The frame clock.\n")
b = t.index("            hc->reg[HcInterruptStatus / 4] |= INTR_SF;\n        }\n", a) + len("            hc->reg[HcInterruptStatus / 4] |= INTR_SF;\n        }\n")
clock = t[a:b]
t = t[:a] + t[b:]
# ... and run it at the end of the tick, after any walk, before the interrupt goes out
rep("""    deliver:
""", """    deliver:
        /* The frame ends here, after the walk (tools_fix_ohci_frame_order.py): a driver
         * that waits for the next frame before freeing TDs must find the controller
         * done with the lists it saw -- the new frame number came before the walk. */
""" + clock)
open(p, 'w').write(t)
print('applied')

"""tools_fix_bus_tag.py -- move XBOX_BUS_RAM_TAG above the 128 MB window (2026-11-12).

The tag marks a device bus address as "ordinary guest RAM, read at its VA" (kernel.h). It was bit 26
(0x04000000): "above any physical address the 64 MB window can produce". With the 128 MB window
(tools_ram128.sh, live since 2026-11-11 17:21) every physical address from 64 to 128 MB HAS bit 26,
so the APU, the NV2A executor and OHCI read those buffers at the wrong place:
  - sound stored high up (music streams, car engine/gear sounds, loaded late) played as distorted
    noise (owner: "the music and car gears");
  - OHCI transfer descriptors up there were misread (the "NextTD holding a virtual pointer" USB
    freeze), and the GPU's push buffer / DMA likely too (the push-buffer-space stall).
Bit 27 (0x08000000) is above every physical address of a 128 MB window, and every tagged VA is
below 128 MB (xbox_devbus.c tags only va < XBOX_CONTIG_SIZE), so OR/strip stay exact.

Run in WSL:  python3 /mnt/c/Games/mc3-web-port/tools_fix_bus_tag.py   (then rebuild)
Idempotent. tools_ram128.sh off would need the tag back at 0x04000000? No: bit 27 is also above a
64 MB window, so it is right for both sizes.
"""
import os, re, sys

SRC = os.path.expanduser('~/mc3-web/xboxrecomp/src')

def edit(rel, old, new):
    p = os.path.join(SRC, rel)
    t = open(p, encoding='utf-8').read()
    if new in t:
        print('already:', rel); return
    if t.count(old) != 1:
        sys.exit('pattern not found once in %s: %r' % (rel, old))
    open(p, 'w', encoding='utf-8').write(t.replace(old, new))
    print('patched:', rel)

edit('kernel/kernel.h',
     '#define XBOX_BUS_RAM_TAG 0x04000000u',
     '#define XBOX_BUS_RAM_TAG 0x08000000u   /* bit 27: above a 128 MB window too (bit 26 was inside it) */')
edit('apu/apu_shim.h',
     '    if ((uint32_t)addr & 0x04000000u)',
     '    if ((uint32_t)addr & 0x08000000u)   /* XBOX_BUS_RAM_TAG (kernel.h) */')
# the APU's physical mask must keep the tag out of the address but leave all 128 MB in
edit('apu/apu_shim.h',
     '    uint32_t p = (uint32_t)addr & 0x07FFFFFF;\n    /* XBOX_BUS_RAM_TAG',
     '    uint32_t p = (uint32_t)addr & 0x07FFFFFF;   /* 128 MB; the tag (bit 27) is outside it */\n    /* XBOX_BUS_RAM_TAG')
print('done: rebuild (tools_build_ghosts.sh NORELIFT=1 is enough: no hook change)')

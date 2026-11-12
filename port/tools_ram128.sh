#!/bin/bash
# tools_ram128.sh [on|off]   a 128 MB contiguous window for the guest (a devkit Xbox's worth) -- or back to 64.
# MC3's main heap runs from the end of its image to MmClaimGpuInstanceMemory's answer, the top of the
# contiguous window minus the GPU reserve (47 MB with a 64 MB window). Real cars and a garage trip with
# them ran it out (2026-11-11), so the window is doubled: the heap should grow to ~111 MB.
# Touches (in ~/mc3-web/xboxrecomp): kernel.h XBOX_CONTIG_SIZE, nv2a_pb_scan.c PB_RAM_BYTES,
# apu_shim.h physical mask, kernel_memory.c TotalPhysicalPages.  Rebuild after (tools_build_ghosts.sh).
set -e
cd ~/mc3-web/xboxrecomp/src
if [ "${1:-on}" = "off" ]; then A=128; B=64; M1=0x07FFFFFF; M0=0x03FFFFFF; else A=64; B=128; M1=0x03FFFFFF; M0=0x07FFFFFF; fi
sed -i "s|#define XBOX_CONTIG_SIZE (${A}u \* 1024u \* 1024u)|#define XBOX_CONTIG_SIZE (${B}u * 1024u * 1024u)|" kernel/kernel.h
sed -i "s|#define PB_RAM_BYTES (${A}u \* 1024u \* 1024u)|#define PB_RAM_BYTES (${B}u * 1024u * 1024u)|" kernel/nv2a_pb_scan.c
sed -i "s|uint32_t p = (uint32_t)addr \& ${M1};|uint32_t p = (uint32_t)addr \& ${M0};|" apu/apu_shim.h
sed -i "s|TotalPhysicalPages = ${A} \* 1024 \* 1024 / page_size;|TotalPhysicalPages = ${B} * 1024 * 1024 / page_size;|" kernel/kernel_memory.c
# the window's size for the game's hooks (minimap_ghosts.inc.c: MC3's heap grows only in a 128 MB window)
grep -q 'xbox_contig_window_mb' kernel/xbox_memory_layout.c || printf '
/* the contiguous window, in MB (tools_ram128.sh) */
unsigned xbox_contig_window_mb(void) { return (unsigned)(XBOX_CONTIG_SIZE >> 20); }
' >> kernel/xbox_memory_layout.c
grep -n 'define XBOX_CONTIG_SIZE' kernel/kernel.h
grep -n 'define PB_RAM_BYTES' kernel/nv2a_pb_scan.c
grep -n 'uint32_t p = (uint32_t)addr' apu/apu_shim.h
grep -n 'TotalPhysicalPages =' kernel/kernel_memory.c

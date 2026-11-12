#!/usr/bin/env python3
"""Near-identity guest layout: host = guest VA + 0x10000, host heap above
the guest's RAM (-sGLOBAL_BASE). Applied to ~/mc3-web in place."""
import pathlib
root = pathlib.Path.home() / "mc3-web"

def edit(rel, a, b):
    p = root / rel
    s = p.read_text()
    if b in s:
        print("already", rel); return
    assert a in s, (rel, a[:70])
    p.write_text(s.replace(a, b, 1))
    print("ok", rel)

edit("xboxrecomp/src/kernel/xbox_memory_layout.c",
     "0x7BFF0000u + XBOX_MAP_START", "0x00010000u + XBOX_MAP_START")
edit("xboxrecomp/src/platform/win32_compat.c",
     "#include <emscripten/heap.h>\n",
     "#include <emscripten/heap.h>\n"
     "#define WASM_HEAP_LO 0x04100000u   /* -sGLOBAL_BASE: the host's data, stack, heap */\n"
     "#define WASM_HEAP_HI 0x74000000u   /* the guest's extended VMA starts here */\n")
edit("xboxrecomp/src/platform/win32_compat.c",
     "    if ((uintptr_t)p + len > 0x78FF0000u)",
     "    if ((uintptr_t)p + len > WASM_HEAP_HI)")
edit("xboxrecomp/src/platform/win32_compat.c",
     "        if ((uintptr_t)address < 0x78FF0000u)\n            free(address);",
     "        if ((uintptr_t)address >= WASM_HEAP_LO && (uintptr_t)address < WASM_HEAP_HI)\n            free(address);")
# the explanation
p = root / "xboxrecomp/src/platform/win32_compat.c"
s = p.read_text()
i = s.find(" * One linear memory, no mmap")
j = s.find(" */\n#include <emscripten/heap.h>")
if i >= 0 and j > i and "near-identity" not in s:
    s = s[:i] + """ * One linear memory, no mmap, no page protection, no aliasing. The memory
 * is grown to 4 GB less 64 KB once, and the guest's address space sits at
 * host = guest VA + 0x10000 (near-identity; xbox_memory_layout.c), so every
 * guest address -- the NV2A and MCPX apertures at 0xFD000000 and up
 * included -- is an ordinary in-bounds address. A base that relied on wasm32
 * wrapping around 4 GB broke wherever the compiler folded a constant into a
 * load's offset, which wasm adds without wrapping. The host's own data,
 * stack and heap start above the guest's RAM (-sGLOBAL_BASE=0x04100000) and
 * must stay under the guest's extended VMA at 0x74000000. Only the last
 * 128 KB of the guest's 4 GB (flash mirrors) fall outside the memory.
 * Fixed-address requests are granted in place; the rest come from the heap.
 * Protection is a no-op.
""" + s[j:]
    p.write_text(s)
    print("ok comment")
edit("CMakeLists.txt",
     "        -sERROR_ON_UNDEFINED_SYMBOLS=1",
     "        -sGLOBAL_BASE=0x04100000 -sERROR_ON_UNDEFINED_SYMBOLS=1")

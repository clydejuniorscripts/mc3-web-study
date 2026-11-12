#!/usr/bin/env python3
"""Fold the tiled aperture onto the contiguous window in the lifted code's
memory macro (the browser has no page aliasing). Patches the template and
the generated header, so a re-lift keeps it."""
import pathlib
root = pathlib.Path.home() / "mc3-web"
OLD = "#define XBOX_PTR(addr) ((uintptr_t)(uint32_t)(addr) + g_xbox_mem_offset)"
NEW = """#if defined(__EMSCRIPTEN__)
/* The browser has no aliasing views. On hardware the tiled aperture
 * 0xF0000000+P and the contiguous window 0x80000000+P are the same bytes
 * (xbox_memory_layout.c); movies decode through the one while the GPU
 * samples the other. So the tiled range is folded onto the contiguous one
 * here, at the cost of a compare per access. */
static inline uintptr_t xbox_ptr_web(uint32_t a)
{
    return (uintptr_t)(a - 0xF0000000u < 0x04000000u ? a - 0x70000000u : a)
           + g_xbox_mem_offset;
}
#define XBOX_PTR(addr) xbox_ptr_web((uint32_t)(addr))
#else
#define XBOX_PTR(addr) ((uintptr_t)(uint32_t)(addr) + g_xbox_mem_offset)
#endif"""
for rel in ["xboxrecomp/templates/runtime/recomp_types.h", "work-dub/gen/recomp_types.h"]:
    p = root / rel
    s = p.read_text()
    if "xbox_ptr_web" in s:
        print("already", rel); continue
    assert s.count(OLD) == 1, (rel, s.count(OLD))
    p.write_text(s.replace(OLD, NEW))
    print("ok", rel)

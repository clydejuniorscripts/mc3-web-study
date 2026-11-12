#!/usr/bin/env python3
"""Name the call site of a skipped null/wild indirect call: the guest return
address on top of the stack, and the next frame's."""
import pathlib
p = pathlib.Path.home() / "mc3-web/src/games/dub/recomp_manual.c"
s = p.read_text()
a = '    fprintf(stderr, "[ICALL] target 0x%08X is not code -- skipped %llu time(s) "'
b = ('    fprintf(stderr, "[ICALL] from ret 0x%08X (next 0x%08X, esp 0x%08X)\\n",\n'
     '            MEM32(g_esp), MEM32(g_esp + 4), g_esp);\n' + a)
if b in s:
    print("already")
else:
    i = s.index("void recomp_icall_not_code_log(uint32_t va)")
    j = s.index(a, i)
    s = s[:j] + b + s[j + len(a):]
    p.write_text(s)
    print("ok")

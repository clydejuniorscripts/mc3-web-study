"""tools_ls_flag.py: the loading-screen loop tells the ghost table when it runs (idempotent).

Edits ~/mc3-web/src/games/dub/recomp_manual.c (run in WSL with python3): sub_0001B500's wrapper
(the loading-screen thread's loop) calls mc3_ghost_ls(1) before the loop and mc3_ghost_ls(0)
after, so the page can show its loading card over in-game reloads (Restart Cruise, Go to Garage)
instead of a black screen. mc3_ghost_ls lives in minimap_ghosts.inc.c (installed at the end).
"""
import os, sys

p = os.path.expanduser('~/mc3-web/src/games/dub/recomp_manual.c')
t = open(p).read()
if 'mc3_ghost_ls(' in t.split('/* >>> mc3-web-port: minimap ghosts')[0]:
    print('already applied'); sys.exit(0)

a = """static RECOMP_TLS int t_ls_thread;          /* this is the loading-screen thread */
void sub_0001B500(void)
{"""
b = """static RECOMP_TLS int t_ls_thread;          /* this is the loading-screen thread */
void mc3_ghost_ls(int on);                  /* minimap_ghosts.inc.c: the page's loading card */
void sub_0001B500(void)
{"""
assert t.count(a) == 1, t.count(a)
t = t.replace(a, b)

a2 = """    t_ls_thread = 1;
    if (nv2a_gl_fill_freeze)
        nv2a_gl_fill_freeze(1);             /* the circle's in and out: no change of size */
    sub_0001B500_gen();
    if (nv2a_gl_fill_freeze)
        nv2a_gl_fill_freeze(-1);
    t_ls_thread = 0;"""
b2 = """    t_ls_thread = 1;
    mc3_ghost_ls(1);
    if (nv2a_gl_fill_freeze)
        nv2a_gl_fill_freeze(1);             /* the circle's in and out: no change of size */
    sub_0001B500_gen();
    if (nv2a_gl_fill_freeze)
        nv2a_gl_fill_freeze(-1);
    mc3_ghost_ls(0);
    t_ls_thread = 0;"""
assert t.count(a2) == 1, t.count(a2)
t = t.replace(a2, b2)
open(p, 'w').write(t)
print('applied')

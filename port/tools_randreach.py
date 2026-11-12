"""tools_randreach.py lo hi [depth]: functions in [lo,hi) whose calls reach rand()'s state (0x47C390)."""
import sys, runpy, os
g = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools_callees.py'), run_name='lib')
lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16); depth = int(sys.argv[3]) if len(sys.argv) > 3 else 4
for f in sorted(g['calls']):
    if lo <= f < hi and g['reaches'](f, depth, set()):
        direct = [c for c in g['calls'][f] if c in g['rand']]
        print('sub_%08X' % f, 'direct rand users called:', ' '.join('sub_%08X' % c for c in dict.fromkeys(direct)))

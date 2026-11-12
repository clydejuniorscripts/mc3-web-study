"""tools_fix_apu_mixmask.py -- choose which APU mixbins reach the speakers, and measure them (2026-11-12).

The DSP is a passthrough stub (apu_dsp.c), so the final mix sums ALL 32 mixbins at full gain. On the
Xbox, DSMIXBIN 0-5 are the speakers (FL FR C LFE BL BR), 6-9 the 3D crosstalk bins, 10 the I3DL2 reverb
send and 11-31 effect sends that the GP DSP program turns into effects. Summed raw, every send adds a
second, unprocessed copy of the sound on top of the dry one. MC3's sound "still horrible" after the bus
tag fix (owner): this lets the page pick the bins without a rebuild.

  RECOMP_APU_MIXDOWN_MASK=<hex>   bins to sum (bit b = bin b). Default: all (as before).
  RECOMP_APU_FXSEND_GAIN=<0..100> gain in % for bins 10..31 that the mask keeps. Default 100.
  RECOMP_APU_BINSTATS=1           every 2 s: "[APU-BINS] b:rms ..." for bins with sound.

Idempotent. Run in WSL, then rebuild (NORELIFT=1).
"""
import os, sys

P = os.path.expanduser('~/mc3-web/xboxrecomp/src/apu/apu_dsp.c')
t = open(P, encoding='utf-8').read()
if 'RECOMP_APU_MIXDOWN_MASK' in t:
    print('already patched'); sys.exit(0)

old_init = '''    s_downmix[10][0] = s_downmix[10][1] = DM_M3DB;  /* I3DL2 reverb send */
}'''
new_init = '''    s_downmix[10][0] = s_downmix[10][1] = DM_M3DB;  /* I3DL2 reverb send */
    {   /* RECOMP_APU_MIXDOWN_MASK / RECOMP_APU_FXSEND_GAIN (tools_fix_apu_mixmask.py) */
        const char *e = getenv("RECOMP_APU_MIXDOWN_MASK");
        unsigned long mask = (e && *e) ? strtoul(e, NULL, 16) : 0xFFFFFFFFul;
        const char *g = getenv("RECOMP_APU_FXSEND_GAIN");
        float fx = (g && *g) ? (float)atoi(g) / 100.0f : 1.0f;
        for (int b = 0; b < NUM_MIXBINS; ++b) {
            float k = ((mask >> b) & 1ul) ? (b >= 10 ? fx : 1.0f) : 0.0f;
            s_downmix[b][0] *= k; s_downmix[b][1] *= k;
        }
        if (e && *e) fprintf(stderr, "[APU] mixdown bins %08lX, effect sends at %.0f%%\\n", mask, fx * 100.0f);
    }
}'''
assert t.count(old_init) == 1, 'downmix_init end not found'
t = t.replace(old_init, new_init)

old_loop = '''                for (int b = 0; b < NUM_MIXBINS; ++b) {
                    left  += s_downmix[b][0] * mixbins[b][i];
                    right += s_downmix[b][1] * mixbins[b][i];
                }'''
new_loop = '''                for (int b = 0; b < NUM_MIXBINS; ++b) {
                    left  += s_downmix[b][0] * mixbins[b][i];
                    right += s_downmix[b][1] * mixbins[b][i];
                    if (s_binstats) s_binsq[b] += (double)mixbins[b][i] * mixbins[b][i];
                }'''
assert t.count(old_loop) == 1, 'mixdown loop not found'
t = t.replace(old_loop, new_loop)

old_fn = 'void mcpx_apu_dsp_frame(MCPXAPUState *d,'
new_fn = '''/* RECOMP_APU_BINSTATS=1: each bin's RMS every 2 s, to see which bins the title feeds */
static int s_binstats = -1;
static double s_binsq[NUM_MIXBINS];
static unsigned s_binn;
static void binstats_frame(void)
{
    if (s_binstats < 0) { const char *e = getenv("RECOMP_APU_BINSTATS"); s_binstats = e && *e && *e != '0'; }
    if (!s_binstats) return;
    s_binn += NUM_SAMPLES_PER_FRAME;
    if (s_binn < 96000) return;
    char line[600]; int o = snprintf(line, sizeof line, "[APU-BINS]");
    for (int b = 0; b < NUM_MIXBINS; ++b) {
        double r = sqrt(s_binsq[b] / s_binn);
        if (r >= 0.001 && o < (int)sizeof line - 16) o += snprintf(line + o, sizeof line - o, " %d:%.3f", b, r);
        s_binsq[b] = 0.0;
    }
    s_binn = 0;
    fprintf(stderr, "%s\\n", line);
}

void mcpx_apu_dsp_frame(MCPXAPUState *d,'''
assert t.count(old_fn) == 1
t = t.replace(old_fn, new_fn)

old_tail = '''    g_dbg.gp.cycles = 0;
    g_dbg.ep.cycles = 0;
}'''
new_tail = '''    binstats_frame();
    g_dbg.gp.cycles = 0;
    g_dbg.ep.cycles = 0;
}'''
assert t.count(old_tail) == 1
t = t.replace(old_tail, new_tail)
if '#include <math.h>' not in t:
    t = '#include <math.h>\n' + t
if '#include <stdlib.h>' not in t:
    t = '#include <stdlib.h>\n' + t
open(P, 'w', encoding='utf-8').write(t)
print('patched', P)

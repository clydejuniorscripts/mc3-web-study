"""tools_fix_apu_downmix.py -- a real stereo downmix for the passthrough DSP (2026-11-12).

Measured on MC3 while driving (RECOMP_APU_BINSTATS): bins 0/1 front, 2 centre, 3 LFE (the LOUDEST,
~0.21 rms: the game sends its full-band engine there for the subwoofer to filter), 4/5 rear, 6-9 the 3D
crosstalk pairs, 10 reverb send. The stub summed rear at 1.0, centre and LFE at 0.71 -- a second,
full-range copy of the engine on top of the dry one (owner: "buzzy, metallic, overdriven").

RECOMP_APU_STEREO_DOWNMIX=1 (the page sets it for MC3; 0 = the old sum):
  L = FL + .71 C + .71 BL + XTLK_FL + .71 XTLK_BL + .5 lowpass120(LFE)      (R the same, right side)
  reverb (10) and effect sends (11-31) left out: they are inputs to DSP effects we don't run.
Idempotent; run after tools_fix_apu_mixmask.py. Rebuild NORELIFT=1.
"""
import os, sys
P = os.path.expanduser('~/mc3-web/xboxrecomp/src/apu/apu_dsp.c')
t = open(P, encoding='utf-8').read()
if 'RECOMP_APU_STEREO_DOWNMIX' in t:
    print('already patched'); sys.exit(0)
assert 'RECOMP_APU_MIXDOWN_MASK' in t, 'run tools_fix_apu_mixmask.py first'

old = '''            float left, right;
            if (mcpx_apu_mixdown_all()) {'''
new = '''            float left, right;
            if (stereo_downmix()) {
                /* tools_fix_apu_downmix.py: front + .71 centre/rear + 3D crosstalk pairs + the
                 * LFE's low end only; reverb/effect sends are DSP inputs and stay out */
                const float k = 0.70710678f;
                s_lfe_lp += 0.0156f * (mixbins[3][i] - s_lfe_lp);   /* one pole, ~120 Hz at 48 kHz */
                left  = mixbins[0][i] + k * mixbins[2][i] + k * mixbins[4][i]
                      + mixbins[6][i] + k * mixbins[8][i] + 0.5f * s_lfe_lp;
                right = mixbins[1][i] + k * mixbins[2][i] + k * mixbins[5][i]
                      + mixbins[7][i] + k * mixbins[9][i] + 0.5f * s_lfe_lp;
                if (s_binstats) for (int b = 0; b < NUM_MIXBINS; ++b) s_binsq[b] += (double)mixbins[b][i] * mixbins[b][i];
            } else if (mcpx_apu_mixdown_all()) {'''
assert t.count(old) == 1, 'mixdown branch not found'
t = t.replace(old, new)

old2 = '/* RECOMP_APU_BINSTATS=1: each bin'
new2 = '''/* RECOMP_APU_STEREO_DOWNMIX (tools_fix_apu_downmix.py) */
static float s_lfe_lp;
static int stereo_downmix(void)
{
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("RECOMP_APU_STEREO_DOWNMIX");
        on = (e && *e) ? (atoi(e) != 0) : 0;
        if (on) fprintf(stderr, "[APU] stereo downmix: front + .71 centre/rear + 3D pairs + LFE low end\\n");
    }
    return on;
}

/* RECOMP_APU_BINSTATS=1: each bin'''
assert t.count(old2) == 1
t = t.replace(old2, new2)
open(P, 'w', encoding='utf-8').write(t)
print('patched', P)

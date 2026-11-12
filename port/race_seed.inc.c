/* >>> mc3-web-port: race seed (installed by install_race_seed.sh; edit
 * C:\Games\mc3-web-port\race_seed.inc.c, not this copy) */

/* ── The same random race for every lobby player (web port, 2026-11-11) ──────
 *
 * The Race Editor's "Generate Random Race" -> Create Race -> Yes runs the random-race
 * generator sub_0011D590 (thiscall, ecx = the editor, [0x4D32FC]); the menu's action
 * sub_0016F640 is only `mov ecx,[0x4D32FC]; jmp sub_0011D590` (found with race_trace.inc.c).
 * The generator has its own LCG (x*214013+2531011, not the C runtime's rand()): on entry it
 * copies the frame counter [0x4FCF34] (one up per frame) into its state [0x47C394], then draws
 * the checkpoint count and each checkpoint from it -- itself, or in sub_0011BC70 for race type 7
 * -- into the course table at 0x478BC4 (byte +4: count; +6 + 6*i: checkpoint i, 6 bytes).
 * So the course depends only on which frame Yes landed on. With a seed armed by the page
 * (web_race_seed), this wrapper puts the seed in the frame counter for the call and puts the
 * frame count back after (same thread: nothing else moves it meanwhile), so the same seed gives
 * the same course on every machine. web_race_seed_result is a hash of the course table the
 * call made: two machines that built the same course from one seed report the same value.
 *
 * Unarmed (the default, and every caller other than the page's race start), it only forwards. */
#include <stdio.h>
#include <stdint.h>
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#else
#ifndef EMSCRIPTEN_KEEPALIVE
#define EMSCRIPTEN_KEEPALIVE
#endif
#endif

static volatile uint32_t rs_seed, rs_armed, rs_after, rs_runs;

/* arm a seed for the next random race the editor generates (one race) */
EMSCRIPTEN_KEEPALIVE void web_race_seed(uint32_t seed)
{
    rs_seed = seed;
    rs_armed = 1;
}

/* the course hash of the last seeded generation; 0 before any */
EMSCRIPTEN_KEEPALIVE uint32_t web_race_seed_result(void)
{
    return rs_after;
}

static uint32_t rs_course_hash(void)
{
    uint32_t n = MEM8(0x478BC8), h = 0x811C9DC5u, a, end;
    if (n > 64) n = 64;
    end = 0x478BCA + 6 * n;
    for (a = 0x478BC4; a < end; a++) { h ^= MEM8(a); h *= 0x01000193u; }
    return h ? h : 1;
}

extern void sub_0011D590_gen(void);
void sub_0011D590(void)
{
    uint32_t frames;
    if (!rs_armed) { sub_0011D590_gen(); return; }
    rs_armed = 0;
    frames = MEM32(0x4FCF34);
    MEM32(0x4FCF34) = rs_seed;
    sub_0011D590_gen();
    MEM32(0x4FCF34) = frames;
    rs_after = rs_course_hash();
    rs_runs++;
    printf("[RACESEED] random race from seed %08X: %u checkpoints, type %u, course hash %08X (run %u)\n",
           (unsigned)rs_seed, (unsigned)MEM8(0x478BC8), (unsigned)MEM8(0x478BC5), (unsigned)rs_after, (unsigned)rs_runs);
}
/* <<< mc3-web-port: race seed */

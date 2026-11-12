#!/usr/bin/env python3
"""Sound in the browser: the APU's output (apu_xaudio2.c, SDL2 queue path)
goes to a ring buffer in the shared wasm memory, which an AudioWorklet on the
page plays. SDL's Emscripten audio opens only on the page's main thread; the
APU frame thread is a worker. Only the handful of SDL audio calls the backend
makes are redirected; its pacing, volume, limiter and dump stay as they are."""
import pathlib
p = pathlib.Path.home() / "mc3-web/xboxrecomp/src/apu/apu_xaudio2.c"
s = p.read_text()
anchor = "#include <stdlib.h>\n#include <SDL.h>\n#if !defined(__SWITCH__)\n"
RING = r'''#include <stdlib.h>
#include <SDL.h>
#if defined(__EMSCRIPTEN__)
/* ── Web Audio output ───────────────────────────────────────────────
 * A single-producer / single-consumer ring of 48 kHz s16 stereo frames in
 * the shared memory: this thread writes, the page's AudioWorklet reads.
 * Header (uint32): [0] frames written, [1] frames read (by the worklet),
 * [2] capacity in frames (power of two), [3] worklet underruns. The page
 * finds it through web_audio_ring() once the backend has opened. */
#include <emscripten.h>
#define WEB_RING_FRAMES 16384u                 /* 341 ms: room above the target queue */
static volatile uint32_t *s_web_ring;          /* header + data */
EMSCRIPTEN_KEEPALIVE uintptr_t web_audio_ring(void) { return (uintptr_t)s_web_ring; }
static int web_audio_open(const SDL_AudioSpec *want, SDL_AudioSpec *have)
{
    if (!s_web_ring) {
        s_web_ring = (volatile uint32_t *)calloc(1, 16 + WEB_RING_FRAMES * 4);
        if (!s_web_ring) return 0;
        s_web_ring[2] = WEB_RING_FRAMES;
    }
    *have = *want;
    return 1;
}
static Uint32 web_audio_queued_bytes(void)
{
    uint32_t w = __atomic_load_n(&s_web_ring[0], __ATOMIC_ACQUIRE);
    uint32_t r = __atomic_load_n(&s_web_ring[1], __ATOMIC_ACQUIRE);
    return (Uint32)((w - r) * 4u);
}
static int web_audio_queue(const void *buf, Uint32 len)
{
    const uint32_t *src = (const uint32_t *)buf;            /* one stereo s16 frame */
    uint32_t frames = len / 4u, w, r, i;
    uint32_t *data = (uint32_t *)(s_web_ring + 4);
    if (!s_web_ring) return -1;
    w = __atomic_load_n(&s_web_ring[0], __ATOMIC_ACQUIRE);
    r = __atomic_load_n(&s_web_ring[1], __ATOMIC_ACQUIRE);
    if (frames > WEB_RING_FRAMES - (w - r))
        frames = WEB_RING_FRAMES - (w - r);                 /* full: the rest is dropped */
    for (i = 0; i < frames; i++)
        data[(w + i) & (WEB_RING_FRAMES - 1u)] = src[i];
    __atomic_store_n(&s_web_ring[0], w + frames, __ATOMIC_RELEASE);
    return 0;
}
#undef SDL_WasInit
#undef SDL_InitSubSystem
#undef SDL_QuitSubSystem
#define SDL_WasInit(x)                       1
#define SDL_InitSubSystem(x)                 0
#define SDL_QuitSubSystem(x)                 ((void)0)
#define SDL_OpenAudioDevice(n, c, want, have, f) web_audio_open((want), (have))
#define SDL_PauseAudioDevice(d, p)           ((void)0)
#define SDL_CloseAudioDevice(d)              ((void)0)
#define SDL_GetQueuedAudioSize(d)            web_audio_queued_bytes()
#define SDL_QueueAudio(d, b, l)              web_audio_queue((b), (l))
#define SDL_GetCurrentAudioDriver()          "Web Audio (AudioWorklet)"
#endif
#if !defined(__SWITCH__)
'''
if "web_audio_ring" in s:
    print("already")
else:
    assert anchor in s
    s = s.replace(anchor, RING, 1)
    p.write_text(s)
    print("ok")
c = pathlib.Path.home() / "mc3-web/CMakeLists.txt"
t = c.read_text()
if "_web_audio_ring" not in t:
    t = t.replace("_web_gl_state,_web_snapshot", "_web_gl_state,_web_snapshot,_web_audio_ring")
    c.write_text(t); print("export ok")

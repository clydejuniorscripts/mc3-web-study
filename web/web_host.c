/* web_host.c -- the browser host: the disc, saves, boot.
 *
 * The game's files are not in the module. The player imports their own disc
 * image in the page; it is copied into the browser's private storage and
 * /game links to it (disc_from_opfs). Without an import (development),
 * /game is a WasmFS fetch-backed
 * directory: each file is fetched from <page>/game/<path> on first read, in
 * 1 MB Range requests, so only what the game reads is downloaded. The list of
 * files (path and size) is embedded at build time (game_manifest.txt) and
 * comes from the player's own extracted disc; the bytes never are.
 * Saves go to /save (memory for now; OPFS next).
 */
#if defined(__EMSCRIPTEN__)
#include <emscripten.h>
#include <emscripten/wasmfs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <strings.h>
#include <stdatomic.h>

/* ── Virtual network transport (web_net) ────────────────────────────────────
 * Two byte rings in shared memory. TX holds frames the guest's network layer
 * produced, which the page's relay bridge drains and sends to the relay; RX
 * holds frames the relay delivered, which the guest consumes. Each record is
 * [u16 length][bytes]. Single producer / single consumer per ring; the indices
 * are absolute byte counts (cap is a power of two, so position = index & (cap-1)
 * stays valid across the 2^32 wrap). The guest NIC hook (next) will push/pop
 * here; until then web_net_test_send / _recv stand in for it so the whole relay
 * path can be exercised. */
#define NET_RING_CAP (1u << 20)
typedef struct {
    _Atomic uint32_t w, r;      /* JS reads/writes these by the same layout */
    uint32_t cap, flags;
    uint8_t  buf[NET_RING_CAP];
} NetRing;
static NetRing *s_net_tx, *s_net_rx;
static volatile int s_net_up;   /* the room is joined: the guest link is "up" */

static void net_copy_in(NetRing *g, uint32_t at, const uint8_t *p, uint32_t n)
{
    uint32_t off = at & (g->cap - 1), first = g->cap - off;
    if (first > n) first = n;
    memcpy(g->buf + off, p, first);
    if (n > first) memcpy(g->buf, p + first, n - first);
}
static void net_copy_out(NetRing *g, uint32_t at, uint8_t *p, uint32_t n)
{
    uint32_t off = at & (g->cap - 1), first = g->cap - off;
    if (first > n) first = n;
    memcpy(p, g->buf + off, first);
    if (n > first) memcpy(p + first, g->buf, n - first);
}
/* Append one frame; 0 if it does not fit. */
static int net_push(NetRing *g, const uint8_t *p, uint32_t n)
{
    uint32_t w, r;
    uint8_t hdr[2];
    if (!g || n == 0 || n > 0xFFFF) return 0;
    w = atomic_load_explicit(&g->w, memory_order_relaxed);
    r = atomic_load_explicit(&g->r, memory_order_acquire);
    if (g->cap - (w - r) < n + 2) return 0;
    hdr[0] = n & 0xFF; hdr[1] = (n >> 8) & 0xFF;
    net_copy_in(g, w, hdr, 2);
    net_copy_in(g, w + 2, p, n);
    atomic_store_explicit(&g->w, w + n + 2, memory_order_release);
    return 1;
}
/* Pop one frame into out (<=cap); returns its length, or -1 if none. */
static int net_pop(NetRing *g, uint8_t *out, uint32_t cap)
{
    uint32_t w, r, n;
    uint8_t hdr[2];
    if (!g) return -1;
    w = atomic_load_explicit(&g->w, memory_order_acquire);
    r = atomic_load_explicit(&g->r, memory_order_relaxed);
    if (w - r < 2) return -1;
    net_copy_out(g, r, hdr, 2);
    n = (uint32_t)hdr[0] | ((uint32_t)hdr[1] << 8);
    if (w - r < 2 + n) return -1;
    net_copy_out(g, r + 2, out, n < cap ? n : cap);
    atomic_store_explicit(&g->r, r + 2 + n, memory_order_release);
    return (int)(n < cap ? n : cap);
}
static void net_init(void)
{
    s_net_tx = (NetRing *)calloc(1, sizeof(NetRing));
    s_net_rx = (NetRing *)calloc(1, sizeof(NetRing));
    if (s_net_tx) s_net_tx->cap = NET_RING_CAP;
    if (s_net_rx) s_net_rx->cap = NET_RING_CAP;
    printf("[WEB] net transport: TX ring %p, RX ring %p\n", (void *)s_net_tx, (void *)s_net_rx);
}
/* For the page's relay bridge (mapped from wasmMemory by the ring base). */
EMSCRIPTEN_KEEPALIVE void *web_net_tx_ring(void) { return s_net_tx; }
EMSCRIPTEN_KEEPALIVE void *web_net_rx_ring(void) { return s_net_rx; }
EMSCRIPTEN_KEEPALIVE void  web_net_set_up(int up) { s_net_up = up; }
EMSCRIPTEN_KEEPALIVE int   web_net_link_up(void) { return s_net_up; }
/* Freeze diagnosis: frames shown so far (stops rising when the game stops drawing),
 * and every guest thread's current kernel call plus the guest lock's holder, to the
 * log as [THREADS] lines (kernel_bridge.c, tools_threads_dump.py). */
extern uint32_t nv2a_gl_frame_count(void) __attribute__((weak));
extern void xbox_threads_dump(void) __attribute__((weak));
EMSCRIPTEN_KEEPALIVE uint32_t web_frame_count(void) { return nv2a_gl_frame_count ? nv2a_gl_frame_count() : 0; }
EMSCRIPTEN_KEEPALIVE void web_threads_dump(void) { if (xbox_threads_dump) xbox_threads_dump(); }
/* Stand-ins for the guest NIC until it is wired: push a frame as if the guest
 * sent it (into TX, which the bridge forwards), and read one the relay left in
 * RX. Two tabs: one web_net_test_send, the other web_net_test_recv. */
EMSCRIPTEN_KEEPALIVE int web_net_test_send(const char *p, int n)
{ return net_push(s_net_tx, (const uint8_t *)p, (uint32_t)n); }
EMSCRIPTEN_KEEPALIVE int web_net_test_recv(char *out, int cap)
{ return net_pop(s_net_rx, (uint8_t *)out, (uint32_t)cap); }
/* For the NIC model (nvnet.c): a guest frame out to the relay, and the next
 * relay frame in for the guest. */
int web_net_tx_push(const unsigned char *p, int n) { return net_push(s_net_tx, (const uint8_t *)p, (uint32_t)n); }
int web_net_rx_pop(unsigned char *out, int cap)    { return net_pop(s_net_rx, (uint8_t *)out, (uint32_t)cap); }

/* Directories and files are made with plain mkdir/open inside the mounted
 * /game: the fetch backend names a child by its path from the mount (and so
 * its URL) only when it is created through its directory. wasmfs_create_file
 * would leave the path empty and every file would fetch <base> itself. */
static void mkdirs(const char *path)
{
    char buf[512];
    size_t n = strlen(path);
    if (n >= sizeof buf) return;
    memcpy(buf, path, n + 1);
    for (char *p = buf + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        struct stat st;
        if (stat(buf, &st) != 0 && mkdir(buf, 0777) != 0)
            fprintf(stderr, "[WEB] mkdir %s: %s\n", buf, strerror(errno));
        *p = '/';
    }
}

/* The player's disc, imported by the page (disc/disc-import.js) into the
 * browser's private storage: OPFS mc3/game/<path>, and mc3/disc.json written
 * last, naming the title and default.xbe's SHA-256. Only MC3: DUB Edition
 * (USA) is accepted. */
#define MC3_TITLE_ID "\"0x54540079\""
#define MC3_XBE_SHA256 "d9db63bb99dc04fd2826886ffc1af2fd76886b268ab6f9395d6164c3ed676c82"

/* /game from the imported disc: /opfs is the browser storage, and /game a
 * memory directory whose entries link to /opfs/mc3/game/<entry>, so the hard
 * disk folders below (UDATA on OPFS, TDATA and CACHE in memory) can still be
 * mounted beside them. 0: no valid import (or WEB_DISC=http asks for the
 * server's files): the caller mounts HTTP. */
static int disc_from_opfs(backend_t opfs)
{
    const char *w = getenv("WEB_DISC");
    char buf[4096];
    size_t n;
    FILE *f;
    DIR *d;
    struct dirent *e;
    int links = 0;
    if ((w && !strcmp(w, "http")) || !opfs)
        return 0;
    if (wasmfs_create_directory("/opfs", 0777, opfs) != 0) {
        fprintf(stderr, "[WEB] cannot mount browser storage at /opfs\n");
        return 0;
    }
    f = fopen("/opfs/mc3/disc.json", "r");
    if (!f) {
        printf("[WEB] no imported disc in browser storage\n");
        return 0;
    }
    n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    buf[n] = 0;
    if (!strstr(buf, MC3_TITLE_ID) || !strstr(buf, MC3_XBE_SHA256)) {
        printf("[WEB] the imported disc is not MC3: DUB Edition (USA); not used\n");
        return 0;
    }
    d = opendir("/opfs/mc3/game");
    if (!d) {
        printf("[WEB] imported disc: no mc3/game folder\n");
        return 0;
    }
    mkdir("/game", 0777);
    while ((e = readdir(d)) != NULL) {
        char from[600], to[600];
        if (e->d_name[0] == '.' || !strcasecmp(e->d_name, "UDATA")
            || !strcasecmp(e->d_name, "TDATA") || !strcasecmp(e->d_name, "CACHE"))
            continue;
        snprintf(from, sizeof from, "/opfs/mc3/game/%s", e->d_name);
        snprintf(to, sizeof to, "/game/%s", e->d_name);
        if (symlink(from, to) == 0)
            links++;
        else
            fprintf(stderr, "[WEB] link %s: %s\n", to, strerror(errno));
    }
    closedir(d);
    printf("[WEB] /game: your disc, from browser storage (%d entries)\n", links);
    return links > 0;
}

void web_boot(void)
{
    backend_t opfs = getenv("WEB_SAVES_MEMORY") ? NULL : wasmfs_create_opfs_backend();
    int files = 0, from_opfs = disc_from_opfs(opfs);
    if (!from_opfs) {
        backend_t be = wasmfs_create_fetch_backend("game", 1u << 20);
        if (!be || wasmfs_create_directory("/game", 0777, be) != 0) {
            fprintf(stderr, "[WEB] cannot mount /game\n");
            return;
        }
        FILE *m = fopen("/web/game_manifest.txt", "r");
        if (!m) { fprintf(stderr, "[WEB] no game manifest\n"); return; }
        char line[600];
        while (fgets(line, sizeof line, m)) {
            char *tab = strchr(line, '\t');
            if (!tab) continue;
            *tab = 0;
            char path[620];
            snprintf(path, sizeof path, "/game/%s", line);
            mkdirs(path);
            int fd = open(path, O_CREAT | O_WRONLY, 0444);
            if (fd < 0)
                fprintf(stderr, "[WEB] file %s: %s\n", path, strerror(errno));
            else {
                close(fd);
                files++;
            }
        }
        fclose(m);
    }
    /* The Xbox hard disk's partition 1 lands in the game folder here
     * (TDATA settings, UDATA saves, CACHE), and the disc mounts are read-only.
     * UDATA -- the saves -- lives in the browser's private storage (OPFS),
     * so a save survives a reload; TDATA and CACHE are scratch, in memory. */
    {
        backend_t mem = wasmfs_create_memory_backend();
        int rc = opfs ? wasmfs_create_directory("/game/UDATA", 0777, opfs) : -1;
        if (rc != 0)
            rc = wasmfs_create_directory("/game/UDATA", 0777, mem);
        printf("[WEB] saves (UDATA): %s\n", rc != 0 ? "UNAVAILABLE" : opfs ? "browser storage (OPFS)" : "memory");
        wasmfs_create_directory("/game/TDATA", 0777, mem);
        wasmfs_create_directory("/game/CACHE", 0777, mem);
    }
    mkdir("/save", 0777);
    setenv("MC3_GAME_DIR", "/game", 1);
    setenv("MC3_SAVE_DIR", "/save", 1);
    /* Sound: the APU's output goes to a ring in shared memory that the
     * page's AudioWorklet plays (audio_fix.py). RECOMP_AUDIO=0 in the URL
     * turns it off (the APU then keeps time by the clock). */
    /* Buffer mapping: nv2a_gl maps without the unsynchronised flag on the
     * web (Emscripten emulates the map; map_fix.py), so mapped streaming and
     * draw merging stay on. RECOMP_GL_MAP=0 / RECOMP_GL_MERGE=0 in the URL
     * still switch them off. */
    /* The guest lock handed over by priority: the main thread (and the
     * time-critical audio thread) pre-empt lower-priority holders. Cross-
     * worker hand-offs cost more here than on a native host; the main
     * thread's wait for the lock fell from ~20% to 5-15% of a race. */
    setenv("RECOMP_GIL_EAGER", "1", 0);
    net_init();
    {   /* The NvNet NIC model (nvnet.c) bridges System Link to the relay, when
         * the title's network stack is on (RECOMP_NET_LINK=1). */
        extern void xbox_nic_init(void);
        xbox_nic_init();
    }
    if (!from_opfs)
        printf("[WEB] /game: %d files over HTTP (the dev server's copy)\n", files);
    if (getenv("WEB_FS_TEST")) {
        extern void web_fs_test_run(void);
        web_fs_test_run();
    }
    {   /* first read: proves the HTTP path before the title needs it */
        struct stat st;
        int rs = stat("/game/default.xbe", &st);
        FILE *f = fopen("/game/default.xbe", "rb");
        printf("[WEB] stat=%d (errno %d) size=%lld fopen=%p (errno %d)\n", rs, errno,
               rs == 0 ? (long long)st.st_size : -1LL, (void *)f, errno);
        if (f) {
            unsigned char b[4] = {0};
            size_t n = fread(b, 1, 4, f);
            fseek(f, 0, SEEK_END);
            printf("[WEB] read %zu: %c%c%c%c, ftell=%ld\n", n, b[0], b[1], b[2], b[3], ftell(f));
            fclose(f);
        }
    }
}

/* Debug (WEB_FS_TEST=1): FNV-1a of a file's first 3 MB read through WasmFS in
 * odd-sized pieces that straddle the fetch backend's chunks, to compare with
 * the same hash of the server's bytes. */
static void web_fs_test(const char *path)
{
    FILE *f = fopen(path, "rb");
    unsigned char buf[4097];
    uint32_t h = 2166136261u;
    size_t n, total = 0;
    if (!f) { printf("[FSTEST] %s: cannot open\n", path); return; }
    while (total < (3u << 20) && (n = fread(buf, 1, sizeof buf, f)) > 0) {
        for (size_t i = 0; i < n && total + i < (3u << 20); i++)
            h = (h ^ buf[i]) * 16777619u;
        total += n;
    }
    fclose(f);
    if (total > (3u << 20)) total = 3u << 20;
    printf("[FSTEST] %s: %zu bytes, fnv %08x\n", path, total, (unsigned)h);
}

static void web_fs_blocks(const char *path)
{
    FILE *f = fopen(path, "rb");
    unsigned char buf[4097];
    uint32_t h = 2166136261u;
    size_t n, pos = 0;
    if (!f) return;
    printf("[FSBLK]");
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        for (size_t i = 0; i < n; i++, pos++) {
            h = (h ^ buf[i]) * 16777619u;
            if ((pos & 0xFFFF) == 0xFFFF) { printf(" %08x", (unsigned)h); h = 2166136261u; }
        }
    }
    printf(" %08x\n", (unsigned)h);
    fclose(f);
}

/* Debug, from the page (Module._web_snapshot()): the watchdog's dump of the
 * title's main thread -- registers, guest stack, the kernel call it is in. */
EMSCRIPTEN_KEEPALIVE void web_snapshot(void)
{
    extern void xbox_WatchdogDump(const char *why);
    xbox_WatchdogDump("web snapshot");
}

static void web_fs_pread(const char *path)
{
    static const long offs[] = { 0, 1048570, 1048576, 1100000, 1333420 };
    int fd = open(path, O_RDONLY);
    if (fd < 0) return;
    printf("[FSPREAD]");
    for (unsigned k = 0; k < sizeof offs / sizeof offs[0]; k++) {
        unsigned char b[8] = {0};
        ssize_t n = pread(fd, b, 8, offs[k]);
        printf(" %ld:%zd:%02x%02x%02x%02x%02x%02x%02x%02x", offs[k], n,
               b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]);
    }
    printf("\n");
    close(fd);
}

void web_fs_test_run(void)
{
    web_fs_pread("/game/video/rockstar.bik");
    web_fs_blocks("/game/video/rockstar.bik");
    web_fs_test("/game/video/rockstar.bik");
    web_fs_test("/game/assets_x.dat");
}

/* Debug: the XBE header and the first kernel thunk, still in guest memory? */
void web_guard(const char *step)
{
    extern ptrdiff_t g_xbox_mem_offset;
    const volatile uint32_t *hdr = (const volatile uint32_t *)((uintptr_t)0x10000u + g_xbox_mem_offset);
    const volatile uint32_t *thk = (const volatile uint32_t *)((uintptr_t)0x411440u + g_xbox_mem_offset);
    fprintf(stderr, "  [GUARD] %s: XBE magic %08x, thunk[0] %08x\n", step, (unsigned)hdr[0], (unsigned)thk[0]);
}
#endif

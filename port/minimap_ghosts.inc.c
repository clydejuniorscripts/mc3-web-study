/* >>> mc3-web-port: minimap ghosts (installed by install_minimap_ghosts.sh; edit
 * C:\Games\mc3-web-port\minimap_ghosts.inc.c, not this copy) */

/* ── Other players on the game's own minimap (web port, 2026-11-10) ──────
 *
 * The HUD map (hudMapLocal, sub_000B3120) draws the racers' arrows -- in Arcade
 * Cruise just the local player's -- with sub_000B0A50 (thiscall, ecx = the map,
 * one pointer argument, ret 4), right after it has put the render state in order
 * for them. An arrow is sub_000AC700(colour, matrix, scale): a 3x4 matrix with
 * the WORLD position at +0x24 and the forward row at +0x18 (it points out of the
 * BACK of a car). Icons that are not the player first pass their position
 * through this->vtbl[0x90](&pos, ref + 0x24, &pos), ref being the matrix the map
 * is centred on, and get an outline first (colour +0x90 of the
 * hudMapLocalShared tunables at [0x4D0620], scale x RacerIconBkgZoomMultiplier
 * +0x1C).
 *
 * Right after the game's own arrows this hook draws one more per remote player,
 * from the table the page fills (web/index.html, mc3ghost: the players it hears
 * about on the relay), in the game's own "other humans" colour (+0x30) at the
 * cruising-hook size (+0xC0), centred on the local player's car matrix
 * (sub_00291900(0) -> sub_00299A60, as sub_000B0A50 itself gets it). In the
 * other direction it publishes that matrix's position and forward row -- where
 * the local player is -- so the page no longer has to hunt for the car in memory.
 *
 * Why exactly there (six builds, same day):
 *  - wrappers around sub_000AF240 (other racers' arrows) and sub_000AE9E0 (the
 *    icon list's icons) never ran in Arcade Cruise;
 *  - one around sub_000B28B0 (the map's moving icons) ran and put the arrows in
 *    the right places, but their colour came and went: in this port
 *    sub_000AC700's plain-coloured triangle is black whenever the texture state
 *    has really been applied before it ([0x4D0CA4] = 0 or [0x4D0BB0] dirty:
 *    black every time, the player's own arrow included) and coloured only on the
 *    state the title's own arrow draw leaves behind. So the extra arrows are
 *    drawn on that very state, with nothing touched in between.
 *
 * On targets with no page nothing ever fills the table and the hook only
 * forwards to the generated body. */
#include <math.h>
#include <string.h>
#include <stdio.h>
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#else
#ifndef EMSCRIPTEN_KEEPALIVE
#define EMSCRIPTEN_KEEPALIVE
#endif
#endif

extern uint32_t nv2a_gl_frame_count(void);
extern void sub_000B0A50_gen(void);
extern void sub_000AC700(void);
extern void sub_00291900(void);
extern void sub_00299A60(void);
static uint32_t s_pc_player;     /* the local player object, from sub_00291900(0) each HUD frame (real cars) */
static void pc_frame(void);      /* real cars, stage 1 (below); once a frame from cars_frame */
static void rc_frame(uint32_t mgr, float now);   /* real cars, stage 2 (below); after the slots */
static void tp_frame(void);      /* teleport (below) */

#define MC3_GHOSTS 16
#define MC3_CARS 8
struct mc3_ghost { float x, y, z, fx, fz; uint32_t on; };   /* 24 bytes; the page writes these.
                                                             * on: 0 = unused, else the player's id
                                                             * (older pages write 1 for everyone) */
struct mc3_car {            /* 48 bytes; a traffic car standing in for a remote player (see below) */
    uint32_t veh;           /* +0   the traffic car (guest address), 0 = slot free */
    uint32_t id;            /* +4   whose it is */
    float x, y, z;          /* +8   where it is drawn (smoothed) */
    float hx, hz;           /* +20  its forward row (out of the back, as the game has it) */
    float vx, vy, vz;       /* +28  its velocity */
    uint32_t age;           /* +40  frames it has been this player's car */
    uint32_t type;          /* +44  the traffic car's type object */
};
static struct mc3_ghost_table {
    uint32_t version;       /* +0   5 */
    uint32_t calls;         /* +4   times the map drew its racer arrows */
    uint32_t drawn;         /* +8   arrows drawn here for other players */
    uint32_t self_seq;      /* +12  bumps whenever self[] is refreshed */
    float    self[8];       /* +16  the local car: x y z, forward row x y z, arrow scale, 1 */
    float    dbg[4];        /* +48  diagnosis: the argument, the player object, the map, the car matrix (as numbers) */
    uint32_t per_frame;     /* +64  arrow passes in the previous frame */
    uint32_t n;             /* +68  ghosts in use */
    struct mc3_ghost g[MC3_GHOSTS];   /* +72 */
    /* -- cars in the world (version 5); the page may change the first five -- */
    uint32_t cars_on;       /* +456 1 = give remote players a car in the world */
    float    car_yoff;      /* +460 added to a player's height (their car's origin vs a traffic car's) */
    float    car_rin;       /* +464 a player this close to the local car gets a car */
    float    car_rout;      /* +468 ... and loses it beyond this */
    float    car_omega;     /* +472 how tightly a car follows its player (1/s) */
    uint32_t car_n;         /* +476 cars in use */
    uint32_t car_claims;    /* +480 traffic cars taken so far */
    uint32_t car_releases;  /* +484 ... given back */
    uint32_t car_knocks;    /* +488 ... knocked off by the local player */
    uint32_t car_frames;    /* +492 frames this ran */
    uint32_t car_pool;      /* +496 traffic cars alive at the last look */
    uint32_t car_mgr;       /* +500 the traffic manager */
    struct mc3_car car[MC3_CARS];     /* +504 */
    uint32_t car_solid;     /* +888 1 = the cars can be hit (see below); the page may change it */
    float    gvel[MC3_GHOSTS][2];     /* +892 each ghost's velocity x z, units/s (the page writes these) */
    uint32_t arrow_mode;    /* +1020 minimap arrows, for diagnosis: bit 0 = no outline */
    float    arrow_lift;    /* +1024 ... the fill's height above its outline (map units) */
    uint32_t quiet;         /* +1028 online: no pedestrians (at city load) and no traffic but
                             *       the other players' cars; the page sets it */
    uint32_t quiet_target;  /* +1032 traffic cars the city is told to keep (diagnosis) */
    uint32_t quiet_removed; /* +1036 traffic cars taken off the streets */
    uint32_t peds_skipped;  /* +1040 city loads without pedestrians */
    uint32_t peds_far;      /* +1044 pedestrian updates given a viewer outside the city */
    uint32_t cars_same_model; /* +1048 1 = a player's car is the same model on every screen */
    /* -- version 6 -- */
    uint32_t car_drawn[MC3_CARS]; /* +1052 car_frames when car k was last drawn (its drawable,
                             *       sub_0006DFB0): a car the game culls -- behind a building
                             *       (mcOccluderSystem) or off screen -- is not drawn, so the
                             *       page hides its name tag (tags showed through walls) */
    uint32_t ls_active;     /* +1084 1 while the game's loading-screen loop runs (sub_0001B500,
                             *       set by its wrapper in recomp_manual.c): the page shows its
                             *       loading card over in-game reloads instead of a black screen */
    uint32_t ls_runs;       /* +1088 times that loop has started */
    uint32_t gclass[MC3_GHOSTS]; /* +1092 the page: what kind of car ghost i chose (1 car,
                             *       2 truck/SUV, 3 van; 0 unknown), so the borrowed traffic car
                             *       is the nearest kind the city has (model_for) */
    /* -- version 7: real cars, stage 1 (a proof: one extra car of the local player's own model) -- */
    uint32_t pc_req;        /* +1156 the page: 1 = build it, 2 = take it away */
    uint32_t pc_state;      /* +1160 0 none, 1 built and drawn, 0xE.. failed at a step */
    uint32_t pc_veh;        /* +1164 its vehicle object (VEH) */
    uint32_t pc_car;        /* +1168 its car (VEH+0xC) */
    float    pc_side;       /* +1172 how far to the local car's side it stands (units; 0 = 4) */
    uint32_t car_max;       /* +1176 the page: other players' cars to draw at most (1..8; 0 = 8),
                             *       from the frame rate; the nearest players get them */
    uint32_t pc_slot;       /* +1180 real cars stage 1: the player slot the factory is given */
    uint32_t pc_swap;       /* +1184 which of the three globals take the showroom's value for the build
                             *       (bit 0 0x4D0780 textures, 1 0x4D08D8, 2 0x4D09F8; 0 = all): the
                             *       city may draw only models registered through its own */
    /* -- version 8: real cars, stage 2 (each nearby player in a real car of the model they chose) -- */
    uint32_t rc_on;         /* +1188 the page: 1 = real cars for the players who have a car slot */
    char     gname[MC3_GHOSTS][16]; /* +1192 the page: ghost i's car, by its internal name (vp_jetta_03) */
    uint32_t rc_built;      /* +1448 real cars built so far */
    uint32_t rc_failed;     /* +1452 builds that failed (name unknown, or a step) */
    uint32_t rc_shown;      /* +1456 real cars drawn this frame */
    uint32_t rc_flip;       /* +1460 the page, tests: bit 0 = turn the real cars round */
    float    rc_yoff;       /* +1464 the page: added to a player's height for their real car */
    uint32_t rc_last;       /* +1468 the last build's result (1, or 0xE.. as pc_state) */
    uint32_t rc_slot[MC3_CARS];   /* +1472 car slot k's real car (its car object; 0 = the traffic car shows) */
    uint32_t rc_room_kb;    /* +1504 the page, tests: heap free (KB) a new model needs to be built (0 = 6400: a
                             *       model takes ~2 MB of the main heap, and the city keeps the rest) */
    /* -- teleport (version 8, untested): the local car put down somewhere (a friend's "join") -- */
    uint32_t tp_req;        /* +1508 the page: 1 = put the local car at tp_x/y/z facing tp_hx/hz */
    float    tp_x, tp_y, tp_z, tp_hx, tp_hz;   /* +1512 where (the car's origin), and a forward row (kept for later: the heading isn't changed yet) */
    uint32_t tp_state;      /* +1532 1 done, 0xE.. failed at a step */
    uint32_t gcolor[MC3_GHOSTS]; /* +1536 the page: ghost i's minimap arrow colour, 0xRRGGBBAA (0 = the game's own) */
    uint8_t  grec[MC3_GHOSTS][224]; /* +1600 the page: ghost i's car record as they sent it -- [0] 1 = present,
                             *       [1..223] = their record's bytes +4..+0xE2 (paint, parts, plate; no pointers):
                             *       their real car is built from it, in their own paint */
    uint32_t self_car;      /* +5184 the local player's car object (VEH+0xC): the page reads the name of the
                             *       model it is drawn with ([[car+0x18]+0xC]) -- the setup record's name can be
                             *       another car's after the load */
    /* -- version 9: the career map's places on the minimap (garage, movers, tournaments) -- */
    uint32_t pl_n;          /* +5188 the page: places in use (0..16) */
    struct mc3_place { float x, z; uint32_t color, kind; } pl[16];   /* +5192 the page: world x z, colour
                             *       0xRRGGBBAA, kind (1 garage, 2 movers, 3 tournament; 0 = off) */
    float    pl_scale;      /* +5448 the page: a place's star size, x the racers' arrow scale (0 = 1.1) */
    float    pl_range;      /* +5452 the page: places further than this from the car are not drawn (0 = all) */
    uint32_t pl_drawn;      /* +5456 places drawn (count, diagnosis) */
    uint32_t pl_marker;     /* +5460 the page, tests: 1 = the old two-arrow marker instead of the game's icon */
    uint32_t pl_uv[4];      /* +5464 the page, tests: the icon's texture rect in 1/256 units (0 0 0 0 = 0 0 256 256) */
    uint32_t pl_tex_last;   /* +5480 the last icon texture bound (diagnosis; 0 = none found) */
    /* -- version 10: name tags through the game's own camera (tag_view, below) -- */
    uint32_t tag_seq;       /* +5484 bumps after each main-view capture (written last) */
    uint32_t tag_frame;     /* +5488 frames the renderer had finished when it was taken (this
                             *       picture is on screen once the count is past it) */
    uint32_t tag_vpw, tag_vph; /* +5492 the main viewport's width and height (pixels) */
    float    tag_view[16];  /* +5500 the view matrix (world -> camera, D3D row vectors) */
    float    tag_proj[16];  /* +5564 the main view's projection: clip = (p, 1) * view * proj,
                             *       picture u = .5 + .5 x/w, v = .5 - .5 y/w */
    float    tag_head;      /* +5628 the page: a tag's point over a traffic car's origin (0 = 1.35) */
    float    tag_lift;      /* +5632 the page: ... and over a real car's roof (its model's top; 0 = 0.25) */
    struct mc3_tag { float u, v, w; uint32_t id; } tag[MC3_CARS];   /* +5636 car slot k's tag point
                             *       on the picture (u, v 0..1, w its depth; id 0 = none or behind) */
    uint32_t tag_calls;     /* +5764 projection builds seen (diagnosis) */
    uint32_t tag_from;      /* +5768 the main view's caller (diagnosis) */
    float    tag_top;       /* +5772 the last real car's model top (diagnosis; 0 = not read) */
} s_ghosts = { .version = 10, .cars_on = 1, .cars_same_model = 1, .car_yoff = -0.2f, .car_rin = 300.0f, .car_rout = 340.0f,
               .car_omega = 10.0f };

_Static_assert(__builtin_offsetof(struct mc3_ghost_table, pl_tex_last) == 5480, "the page reads fixed offsets");
_Static_assert(__builtin_offsetof(struct mc3_ghost_table, tag_seq) == 5484 &&
               __builtin_offsetof(struct mc3_ghost_table, tag[0]) == 5636 &&
               __builtin_offsetof(struct mc3_ghost_table, tag_top) == 5772, "the page reads fixed offsets");
EMSCRIPTEN_KEEPALIVE void *web_ghost_table(void) { return &s_ghosts; }
/* the loading-screen loop starts (1) / ends (0); called from sub_0001B500's wrapper */
static void rc_drop_all(void);   /* real cars out of the level before it is torn down (below) */
void mc3_ghost_ls(int on) { s_ghosts.ls_active = on ? 1u : 0u; if (on) { s_ghosts.ls_runs++; rc_drop_all(); } }
static void quiet_targets(void);   /* online: empty streets (below) */

static uint32_t ghost_f2u(float f) { union { float f; uint32_t u; } v; v.f = f; return v.u; }
static float ghost_u2f(uint32_t u);
/* Each player's own arrow colour (gcolor, from the page): the arrow takes its colour as a guest
 * address of 4 floats (RGBA; the game's "other humans" one is the tunables' +0x30), so the colours
 * go into 16 x 16 bytes of guest memory taken from the game's allocator (sub_00198790) once per
 * HUD tunables block, i.e. per level (256 bytes; the level's teardown takes it). */
extern void sub_00198790(void);
static uint32_t s_colbuf, s_colbuf_params;
static uint32_t ghost_colour(uint32_t params, uint32_t k)
{
    uint32_t c = s_ghosts.gcolor[k], at;
    if (!c || k >= MC3_GHOSTS) return params + 0x30u;
    if (params != s_colbuf_params) {
        uint32_t esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        PUSH32(g_esp, 16u * MC3_GHOSTS); PUSH32(g_esp, 0x0029D0CBu);
        sub_00198790();
        s_colbuf = g_eax; s_colbuf_params = params;
        g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }
    if (!s_colbuf || (s_colbuf & 3u)) return params + 0x30u;
    at = s_colbuf + 16u * k;
    MEMF(at) = (float)((c >> 24) & 0xFFu) / 255.0f; MEMF(at + 4u) = (float)((c >> 16) & 0xFFu) / 255.0f;
    MEMF(at + 8u) = (float)((c >> 8) & 0xFFu) / 255.0f; MEMF(at + 12u) = (float)(c & 0xFFu) / 255.0f;
    return at;
}
static float ghost_u2f(uint32_t u) { union { float f; uint32_t u; } v; v.u = u; return v.f; }
/* the places' colours: 16 x 16 bytes of guest memory, as ghost_colour's (per HUD tunables block) */
static uint32_t s_plcol, s_plcol_params;
static uint32_t place_colour(uint32_t params, uint32_t k, uint32_t c)
{
    uint32_t at;
    if (params != s_plcol_params) {
        uint32_t esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        PUSH32(g_esp, 16u * 17u); PUSH32(g_esp, 0x0029D0CBu);   /* 16 places + white (the icons' colour) */
        sub_00198790();
        s_plcol = g_eax; s_plcol_params = params;
        g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }
    if (!s_plcol || (s_plcol & 3u) || k >= 17u) return 0;
    at = s_plcol + 16u * k;
    MEMF(at) = (float)((c >> 24) & 0xFFu) / 255.0f; MEMF(at + 4u) = (float)((c >> 16) & 0xFFu) / 255.0f;
    MEMF(at + 8u) = (float)((c >> 8) & 0xFFu) / 255.0f; MEMF(at + 12u) = (float)(c & 0xFFu) / 255.0f;
    return at;
}
/* A place's icon on the minimap, drawn the way the game draws its textured map icons (sub_000AEE60,
 * sub_000AF610): the texture bound as the map's current one ([0x4D0CA4] / [0x4D0C0C], applied by its
 * vtbl+0x24(0) when it changes), a matrix at the place put through the map's world->map transform
 * (this->vtbl[0x90]), then sub_000AC960(this; colour RGBA floats*, matrix*, size, u, v, w, h) -- the
 * texture rect in 1/256 units -- ret 0x1C. The textures are the map's own (sub_000AE7B0 loads them):
 * +0x98 icon_garage, +0x9C icon_trophy, +0xA0 icon_warehouse (the movers' truck), +0xA4 icon_star.
 * Owner, 2026-11-12: "the markers ... are using the wrong icon on the large map and minimap". */
extern void sub_000AC960(void);
static int ghost_va_ok(uint32_t va);
static int place_icon(uint32_t map, uint32_t ref, uint32_t tex, uint32_t colour, float size, float x, float y, float z)
{
    uint32_t sp0 = g_esp, m, target;
    recomp_func_t fn;
    if (!ghost_va_ok(tex) || !ghost_va_ok(MEM32(tex))) return 0;
    if (tex != MEM32(0x004D0CA4u)) {                 /* bind it, as the game does */
        uint32_t f24 = MEM32(MEM32(tex) + 0x24u);
        recomp_func_t bind = recomp_lookup_manual(f24);
        if (!bind) bind = recomp_lookup(f24);
        if (!bind) return 0;
        PUSH32(g_esp, 0u);
        g_ecx = tex;
        PUSH32(g_esp, 0x000AEF2Bu);
        bind();
        g_esp = sp0;
    }
    MEM32(0x004D0CA4u) = tex;
    MEM32(0x004D0C0Cu) = tex;
    s_ghosts.pl_tex_last = tex;

    g_esp -= 0x40;
    m = g_esp;
    MEMF(m + 0x00) = 1.0f; MEMF(m + 0x04) = 0.0f; MEMF(m + 0x08) = 0.0f;
    MEMF(m + 0x0C) = 0.0f; MEMF(m + 0x10) = 1.0f; MEMF(m + 0x14) = 0.0f;
    MEMF(m + 0x18) = 0.0f; MEMF(m + 0x1C) = 0.0f; MEMF(m + 0x20) = 1.0f;
    MEMF(m + 0x24) = x;    MEMF(m + 0x28) = y;    MEMF(m + 0x2C) = z;
    target = MEM32(MEM32(map) + 0x90u);
    fn = recomp_lookup_manual(target);
    if (!fn) fn = recomp_lookup(target);
    if (!fn) { g_esp = sp0; return 0; }
    {
        uint32_t saved = g_esp;
        PUSH32(g_esp, m + 0x24u);
        PUSH32(g_esp, ref + 0x24u);
        PUSH32(g_esp, m + 0x24u);
        g_ecx = map;
        PUSH32(g_esp, 0x000AF69Cu);
        fn();
        g_esp = saved;
    }
    {
        uint32_t u = s_ghosts.pl_uv[0], v = s_ghosts.pl_uv[1], w = s_ghosts.pl_uv[2], h = s_ghosts.pl_uv[3];
        if (!w || !h) { u = 0; v = 0; w = 256u; h = 256u; }
        PUSH32(g_esp, h); PUSH32(g_esp, w); PUSH32(g_esp, v); PUSH32(g_esp, u);
    }
    PUSH32(g_esp, ghost_f2u(size));
    PUSH32(g_esp, m);
    PUSH32(g_esp, colour);
    g_ecx = map;
    PUSH32(g_esp, 0x000AF6D8u);
    sub_000AC960();
    g_esp = sp0;
    return 1;
}

/* guest RAM (the title's heap) or a thread's stack: somewhere a matrix can be */
static int ghost_va_ok(uint32_t va)
{
    return (va >= 0x00010000u && va < 0x10000000u) || (va >= 0x80000000u && va < 0x88000000u);
}

/* One arrow at a world position, as the game draws a racer's. */
static void ghost_arrow(uint32_t map, uint32_t ref, uint32_t fill, uint32_t outline,
                        uint32_t scale_bits, const struct mc3_ghost *g)
{
    uint32_t sp0 = g_esp, m, params = MEM32(0x004D0620u);
    float zoom = params ? MEMF(params + 0x1Cu) : 1.0f;

    g_esp -= 0x40;                       /* the 3x4 matrix, on the guest stack */
    m = g_esp;
    MEMF(m + 0x00) = g->fz;  MEMF(m + 0x04) = 0.0f; MEMF(m + 0x08) = -g->fx;   /* right */
    MEMF(m + 0x0C) = 0.0f;   MEMF(m + 0x10) = 1.0f; MEMF(m + 0x14) = 0.0f;     /* up */
    MEMF(m + 0x18) = g->fx;  MEMF(m + 0x1C) = 0.0f; MEMF(m + 0x20) = g->fz;    /* forward */
    MEMF(m + 0x24) = g->x;   MEMF(m + 0x28) = g->y; MEMF(m + 0x2C) = g->z;     /* position */

    {   /* this->vtbl[0x90](&pos, ref + 0x24, &pos); the callee pops its arguments */
        uint32_t saved = g_esp;
        uint32_t target = MEM32(MEM32(map) + 0x90u);
        recomp_func_t fn = recomp_lookup_manual(target);
        if (!fn)
            fn = recomp_lookup(target);
        if (!fn) {                       /* no such function: draw nothing rather than garbage */
            g_esp = sp0;
            return;
        }
        PUSH32(g_esp, m + 0x24u);
        PUSH32(g_esp, ref + 0x24u);
        PUSH32(g_esp, m + 0x24u);
        g_ecx = map;
        PUSH32(g_esp, 0x000AF2B1u);
        fn();
        g_esp = saved;                   /* whatever it did, the matrix is still at m */
    }

    if (!(s_ghosts.arrow_mode & 1u)) {
    PUSH32(g_esp, ghost_f2u(ghost_u2f(scale_bits) * zoom));   /* the outline */
    PUSH32(g_esp, m);
    PUSH32(g_esp, outline);
    g_ecx = map;
    PUSH32(g_esp, 0x000AF2CDu);
    sub_000AC700();
    }

    g_esp = m;
    MEMF(m + 0x28) += s_ghosts.arrow_lift;
    PUSH32(g_esp, scale_bits);                                /* the arrow */
    PUSH32(g_esp, m);
    PUSH32(g_esp, fill);
    g_ecx = map;
    PUSH32(g_esp, 0x000AF2E3u);
    sub_000AC700();

    g_esp = sp0;
    s_ghosts.drawn++;
}

void sub_000B0A50(void)
{
    static uint32_t cur_frame = 0xFFFFFFFFu, cur_calls;
    uint32_t map = g_ecx, arg = MEM32(g_esp + 0x04u);
    uint32_t frame = nv2a_gl_frame_count();

    if (frame != cur_frame) { s_ghosts.per_frame = cur_calls; cur_calls = 0; cur_frame = frame; }
    cur_calls++;
    s_ghosts.calls++;

    sub_000B0A50_gen();                  /* the game's own arrows; pops its argument */

    /* Every call, like the game's own arrow. This used to be "once per map per frame",
     * keyed on the renderer's frame count -- but the renderer runs on its own thread and
     * counts the frames it has finished, so whenever the game got a frame ahead of it the
     * count had not moved and the other players' arrows were skipped for that whole frame:
     * they flashed off ~4% of frames (2026-11-11, owner: "minimap still flash"). The game
     * calls this once per map per frame (per_frame = 1). */
    if (ghost_va_ok(map)) {
        uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp;
        uint32_t eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        uint32_t params = MEM32(0x004D0620u), player, mtx = 0;

        PUSH32(g_esp, 0);                /* the local player (cdecl) and its car matrix */
        PUSH32(g_esp, 0x000B0A83u);
        sub_00291900();
        player = g_eax;
        if (ghost_va_ok(player)) {
            s_pc_player = player;
            if (ghost_va_ok(MEM32(player + 0x14u))) s_ghosts.self_car = MEM32(MEM32(player + 0x14u) + 0xCu);
        }
        g_esp = esp0;
        if (ghost_va_ok(player)) {
            g_ecx = player;
            PUSH32(g_esp, 0x000B0A8Du);
            sub_00299A60();
            mtx = g_eax;
            g_esp = esp0;
        }
        s_ghosts.dbg[0] = (float)arg; s_ghosts.dbg[1] = (float)player;
        s_ghosts.dbg[2] = (float)map; s_ghosts.dbg[3] = (float)mtx;

        if (ghost_va_ok(mtx)) {
            quiet_targets();
            s_ghosts.self[0] = MEMF(mtx + 0x24u); s_ghosts.self[1] = MEMF(mtx + 0x28u);
            s_ghosts.self[2] = MEMF(mtx + 0x2Cu);
            s_ghosts.self[3] = MEMF(mtx + 0x18u); s_ghosts.self[4] = MEMF(mtx + 0x1Cu);
            s_ghosts.self[5] = MEMF(mtx + 0x20u);
            s_ghosts.self[6] = params ? MEMF(params + 0xC0u) : 0.0f;
            s_ghosts.self[7] = 1.0f;
            s_ghosts.self_seq++;

            if (params && s_ghosts.n) {
                uint32_t n = s_ghosts.n, k;
                float scale = MEMF(params + 0xC0u);          /* CruisingHookScale */
                if (!(scale > 0.0f) || !isfinite(scale))
                    scale = 10.0f;
                if (n > MC3_GHOSTS) n = MC3_GHOSTS;
                for (k = 0; k < n; k++) {
                    struct mc3_ghost gh = s_ghosts.g[k];     /* the page may be writing: take a copy */
                    if (!gh.on || !isfinite(gh.x) || !isfinite(gh.z) || !isfinite(gh.fx) || !isfinite(gh.fz))
                        continue;
                    ghost_arrow(map, mtx, ghost_colour(params, k), params + 0x90u, ghost_f2u(scale), &gh);
                }
            }
            /* the places (version 9): a six-pointed star each -- two arrows, one pointing north and one
             * south, in the place's colour -- so they don't look like a player; drawn after the players'
             * arrows (right after the game's own arrow, where the colours come out right) */
            if (params && s_ghosts.pl_n) {
                uint32_t n = s_ghosts.pl_n, k;
                float scale = MEMF(params + 0xC0u), mul = s_ghosts.pl_scale, rng = s_ghosts.pl_range;
                float px = s_ghosts.self[0], pz = s_ghosts.self[2];
                if (!(scale > 0.0f) || !isfinite(scale)) scale = 10.0f;
                if (!(mul > 0.0f) || !isfinite(mul)) mul = 1.1f;
                if (n > 16u) n = 16u;
                for (k = 0; k < n; k++) {
                    struct mc3_place pl = s_ghosts.pl[k];
                    struct mc3_ghost gh;
                    uint32_t col;
                    if (!pl.kind || !isfinite(pl.x) || !isfinite(pl.z)) continue;
                    if (rng > 0.0f && (pl.x - px) * (pl.x - px) + (pl.z - pz) * (pl.z - pz) > rng * rng) continue;
                    if (!s_ghosts.pl_marker) {               /* the game's own icon for it */
                        static const uint32_t tex_at[5] = { 0u, 0x98u, 0xA0u, 0x9Cu, 0xA4u };   /* kind 1 garage, 2 movers, 3 tournament, 4 meet-up */
                        uint32_t white = place_colour(params, 16u, 0xFFFFFFFFu);
                        if (pl.kind <= 4u && white &&
                            place_icon(map, mtx, MEM32(map + tex_at[pl.kind]), white, scale * mul, pl.x, s_ghosts.self[1], pl.z)) {
                            s_ghosts.pl_drawn++;
                            continue;
                        }
                    }
                    col = place_colour(params, k, pl.color);
                    if (!col) col = params + 0x30u;
                    gh.x = pl.x; gh.y = s_ghosts.self[1]; gh.z = pl.z; gh.on = 1u;
                    gh.fx = 0.0f; gh.fz = 1.0f;
                    ghost_arrow(map, mtx, col, params + 0x90u, ghost_f2u(scale * mul), &gh);
                    gh.fz = -1.0f;
                    ghost_arrow(map, mtx, col, params + 0x90u, ghost_f2u(scale * mul), &gh);
                    s_ghosts.drawn -= 2u;                    /* drawn counts players' arrows */
                    s_ghosts.pl_drawn++;
                }
            }
        }
        g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0;
        g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }
}
/* ── Other players as real cars in the world (web port, 2026-11-11) ───────
 *
 * The city's traffic ("ambient vehicles") is a pool of 0x21C-byte cars in one array:
 * the traffic manager is [[0x4CA64C] + 8], its array [mgr + 0x130], count (word)
 * [mgr + 0x12C]. A car is three objects in one: a world-grid entity at +0 (vtable
 * 0x416D3C; vtbl[4] returns its matrix), a drawable at +0x10 (vtable 0x416D24; draw =
 * sub_0006DFB0; it is culled and drawn from the matrix position alone) and a physics
 * entity at +0x24 (vtable 0x416C90; +0x2C = the word handle of its instance in the
 * physics level [0x518B78], 0xFFFF = the car is not in the world). Its matrix is a 3x4
 * at +0x34 (right, up, forward -- which points out of the back, as on the player's car --
 * and position at +0x58), with the previous frame's at +0x74. Normally a car runs on
 * rails: sub_00079C30(mgr; car, dt) -> sub_00072170 moves it along its road link
 * (+0xFC, parameter +0xF0, speed +0xE0), puts the point in +0xC8 and the direction in
 * +0xD4, rebuilds the matrix from those (sub_000703A0) and tells the physics level
 * ([0x518B78]->vtbl[0x20](handle)) and the world grid (sub_0028A100([0x519280], car)).
 * A car the player hits leaves the rails and becomes a physical object (+0x13C set).
 *
 * To show a remote player, one of these cars is borrowed: the game keeps running it
 * on its rails exactly as before (so the traffic behind it keeps flowing -- it just
 * follows a car nobody sees), and right after each of its updates, and once per frame
 * for all of them, the matrix is replaced by the remote player's position and heading,
 * and the level and the grid are told, as the game itself does after moving a car. So
 * the game draws and lights it like any traffic car, where the other player is.
 * The second hook, around sub_00079B40 (which takes a car out of the world once its road
 * position is out of every viewer's range), keeps a borrowed car alive while its unseen
 * rails position wanders off.
 *
 * Collisions are off by default: neither the physics level nor the world grid is told
 * about the new position, so both still have the car on its rails while the car's own
 * matrix says otherwise, and nothing ever touches it (with only the level left out, local
 * traffic still found the car through the grid and crashed into it). Traffic is not the same on any two players'
 * screens, so a remote player drives straight through local traffic all the time; with
 * the level told (car_solid = 1, tried 2026-11-11) every such overlap knocks the car off
 * its rails into a physical wreck (+0x13C) -- about one a minute with three bots -- and
 * the player has to be given another car. The local player could ram them (it worked),
 * but one-sided hits are not worth cars exploding off other players at random.
 *
 * Positions come from the same table as the minimap arrows (the page fills it from the
 * relay), smoothed here with a critically damped spring so a car glides between the
 * network updates. The cars are whatever civilian models the city has loaded. */
extern void sub_00079C30_gen(void);
extern void sub_00079B40_gen(void);
extern void sub_0028A100(void);

#define CAR_VTBL  0x00416D3Cu
#define CAR_SIZE  0x21Cu
#define CAR_TIME  0x004FCF28u            /* the game clock the traffic runs on (float seconds) */

static float    s_car_cur[MC3_CARS][12], s_car_prev[MC3_CARS][12];   /* this frame's and last frame's matrix */
static float    s_car_last_time = -1.0f;
static struct { float x, y, z, t; } s_car_tgt[MC3_CARS];           /* the last position heard, and when */
static struct { uint32_t id; float until; } s_car_cool[MC3_CARS];    /* players whose car was just knocked off */

static int car_slot_of(uint32_t veh)
{
    int i;
    if (!veh) return -1;
    for (i = 0; i < MC3_CARS; i++)
        if (s_ghosts.car[i].veh == veh) return i;
    return -1;
}

/* is this a live traffic car of this manager's pool? */
static int car_live(uint32_t mgr, uint32_t veh)
{
    uint32_t arr, cnt;
    if (!ghost_va_ok(mgr)) return 0;
    arr = MEM32(mgr + 0x130u); cnt = MEM16(mgr + 0x12Cu);
    if (!ghost_va_ok(arr) || cnt == 0 || cnt > 1024) return 0;
    if (veh < arr || veh >= arr + cnt * CAR_SIZE || (veh - arr) % CAR_SIZE) return 0;
    return MEM32(veh) == CAR_VTBL && MEM16(veh + 0x2Cu) != 0xFFFFu;
}

/* tell the physics level where a car is now: level->vtbl[0x20](handle) */
static void car_tell_level(uint32_t veh)
{
    uint32_t sp0 = g_esp, lvl = MEM32(0x00518B78u), handle = MEM16(veh + 0x2Cu);
    if (handle != 0xFFFFu && ghost_va_ok(lvl) && MEM32(lvl)) {
        uint32_t target = MEM32(MEM32(lvl) + 0x20u);
        recomp_func_t fn = recomp_lookup_manual(target);
        if (!fn) fn = recomp_lookup(target);
        if (fn) {
            PUSH32(g_esp, handle);
            g_ecx = lvl;
            PUSH32(g_esp, 0x000722F7u);
            fn();
        }
        g_esp = sp0;
    }
}

/* tell the world grid (what traffic and the renderer look cars up in) where a car is */
static void car_tell_grid(uint32_t veh)
{
    uint32_t sp0 = g_esp, grid = MEM32(0x00519280u);
    if (ghost_va_ok(grid)) {             /* sub_0028A100(grid; car), ret 4 */
        PUSH32(g_esp, veh);
        g_ecx = grid;
        PUSH32(g_esp, 0x00079D0Fu);
        sub_0028A100();
        g_esp = sp0;
    }
}

/* far below the city: where a borrowed car's physics body, and a spare car, are kept */
static void car_put_far(uint32_t veh)
{
    static const float far_m[12] = { 1, 0, 0,  0, 1, 0,  0, 0, 1,  0, -3000.0f, 0 };
    int k;
    for (k = 0; k < 12; k++) {
        MEMF(veh + 0x34u + 4u * (uint32_t)k) = far_m[k];
        MEMF(veh + 0x74u + 4u * (uint32_t)k) = far_m[k];
    }
    MEMF(veh + 0x58u) = MEMF(veh + 0xC8u); MEMF(veh + 0x60u) = MEMF(veh + 0xD0u);   /* under its road */
    MEMF(veh + 0x98u) = MEMF(veh + 0xC8u); MEMF(veh + 0xA0u) = MEMF(veh + 0xD0u);
}

/* write a borrowed car's matrix and tell the world, as the game does after moving one.
 * Collisions off (car_solid 0, the default): its physics body goes far below the city
 * first -- otherwise it stays on the car's unseen rails, an invisible car to run into --
 * and the drawn matrix is written after. The world grid gets the drawn position only
 * online, where there is no other traffic to drive into it. */
static void car_write(uint32_t veh, int slot)
{
    int k;
    /* the player has a real car (rc_frame): their borrowed traffic car stays out of sight. This
     * write runs again after the game's own update of the car (sub_00079C30) and put it back on
     * the player's spot every frame, so both cars were drawn, one inside the other (owner,
     * 2026-11-12: "BotRico is spawning 2 cars"). The name tag goes by car_drawn, which the traffic
     * car's draw set: the real car counts as drawn instead (no occlusion check for it yet). */
    if (slot >= 0 && slot < MC3_CARS && s_ghosts.rc_slot[slot]) {
        car_put_far(veh);
        car_tell_level(veh);
        s_ghosts.car_drawn[slot] = s_ghosts.car_frames;
        return;
    }
    if (!s_ghosts.car_solid) {
        car_put_far(veh);
        car_tell_level(veh);
    }
    for (k = 0; k < 12; k++) {
        MEMF(veh + 0x34u + 4u * (uint32_t)k) = s_car_cur[slot][k];
        MEMF(veh + 0x74u + 4u * (uint32_t)k) = s_car_prev[slot][k];
    }
    if (s_ghosts.car_solid || s_ghosts.quiet)
        car_tell_grid(veh);
    if (s_ghosts.car_solid)
        car_tell_level(veh);
}

/* Online, spare traffic cars are kept out of sight, ready for the next player who comes
 * near (the city only puts cars on roads as they come into range, so asking it for one
 * when a player turns up can take a long time if nobody moves). */
#define CAR_SPARES 2
static uint32_t s_spare[CAR_SPARES];
static int spare_of(uint32_t veh)
{
    int k;
    for (k = 0; k < CAR_SPARES; k++) if (veh && s_spare[k] == veh) return k;
    return -1;
}

static void car_matrix(float *m, const struct mc3_car *c)
{
    m[0] = c->hz;  m[1] = 0.0f;  m[2] = -c->hx;      /* right */
    m[3] = 0.0f;   m[4] = 1.0f;  m[5] = 0.0f;        /* up */
    m[6] = c->hx;  m[7] = 0.0f;  m[8] = c->hz;       /* forward (out of the back) */
    m[9] = c->x;   m[10] = c->y; m[11] = c->z;       /* position */
}

static void car_free(int slot, int knocked, float now)
{
    struct mc3_car *c = &s_ghosts.car[slot];
    if (knocked) {
        int k, at = 0;
        for (k = 0; k < MC3_CARS; k++) {
            if (s_car_cool[k].id == c->id) { at = k; break; }
            if (s_car_cool[k].until < s_car_cool[at].until) at = k;
        }
        s_car_cool[at].id = c->id; s_car_cool[at].until = now + 4.0f;
        s_ghosts.car_knocks++;
    }
    c->veh = 0; c->id = 0; c->age = 0;
    s_ghosts.car_releases++;
}

/* the traffic car to borrow: a plain one on its rails, the farthest from the local
 * player (the least likely to be looked at as it vanishes), preferring car-sized ones */
static uint32_t car_pick(uint32_t mgr, float px, float pz)
{
    uint32_t arr = MEM32(mgr + 0x130u), cnt = MEM16(mgr + 0x12Cu), i, best = 0, alive = 0;
    float best_score = -1.0e30f;
    for (i = 0; i < cnt; i++) {
        uint32_t veh = arr + i * CAR_SIZE, type;
        float dx, dz, score;
        if (MEM32(veh) != CAR_VTBL || MEM16(veh + 0x2Cu) == 0xFFFFu) continue;
        alive++;
        if (MEM32(veh + 0x13Cu) || !MEM32(veh + 0xFCu) || MEM32(veh + 0xC4u) == 1u ||
            MEM32(veh + 0xECu) || MEM32(veh + 0xA8u) || MEM8(veh + 0xADu) ||
            MEM8(veh + 0x14Eu) || MEM8(veh + 0x14Bu) >= 0x7Fu) continue;
        if (car_slot_of(veh) >= 0) continue;
        type = MEM32(veh + 0x138u);
        if (!ghost_va_ok(type)) continue;
        dx = MEMF(veh + 0x58u) - px; dz = MEMF(veh + 0x60u) - pz;
        score = dx * dx + dz * dz;
        if (!isfinite(score)) continue;
        if (MEMF(type + 0x298u) > 2.4f) score -= 1.0e9f;         /* a bus or a truck: only if nothing else */
        if (score > best_score) { best_score = score; best = veh; }
    }
    s_ghosts.car_pool = alive;
    return best;
}

/* once per game frame: who has a car, who gets one, where each one is now */
static void cars_frame(uint32_t mgr, float now)
{
    float dt = now - s_car_last_time, px, pz, rin, rout, w;
    uint32_t n = s_ghosts.n, key[MC3_GHOSTS];
    struct mc3_ghost gh[MC3_GHOSTS];
    int i, k, used = 0, lim;

    s_car_last_time = now;
    pc_frame();
    tp_frame();
    if (!(dt > 0.0f)) dt = 0.0f;
    if (dt > 0.1f) dt = 0.1f;
    s_ghosts.car_frames++;
    s_ghosts.car_mgr = mgr;
    if (n > MC3_GHOSTS) n = MC3_GHOSTS;
    if (!s_ghosts.cars_on || s_ghosts.self[7] != 1.0f) n = 0;
    px = s_ghosts.self[0]; pz = s_ghosts.self[2];
    rin = s_ghosts.car_rin; rout = s_ghosts.car_rout; w = s_ghosts.car_omega;
    if (!(rin > 10.0f)) rin = 300.0f;
    if (!(rout > rin)) rout = rin + 40.0f;
    if (!(w > 0.5f) || w > 60.0f) w = 10.0f;

    for (i = 0; i < (int)n; i++) {       /* the page may be writing: take copies */
        gh[i] = s_ghosts.g[i];
        key[i] = gh[i].on == 1u ? 0x80000000u + (uint32_t)i : gh[i].on;
        if (!isfinite(gh[i].x) || !isfinite(gh[i].y) || !isfinite(gh[i].z) ||
            !isfinite(gh[i].fx) || !isfinite(gh[i].fz) || (gh[i].fx == 0.0f && gh[i].fz == 0.0f))
            key[i] = 0;
    }

    for (k = 0; k < MC3_CARS; k++) {     /* cars in use: still wanted, still there? */
        struct mc3_car *c = &s_ghosts.car[k];
        float dx, dz, d2, tx, ty, tz, hx, hz, hl, a, kh;
        if (!c->veh) continue;
        if (!car_live(mgr, c->veh)) { car_free(k, 0, now); continue; }      /* the game took it away */
        if (MEM32(c->veh + 0x13Cu)) { car_free(k, 1, now); continue; }      /* knocked off its rails */
        for (i = 0; i < (int)n; i++) if (key[i] && key[i] == c->id) break;
        if (i == (int)n) { car_free(k, 0, now); continue; }                 /* the player left */
        dx = gh[i].x - px; dz = gh[i].z - pz; d2 = dx * dx + dz * dz;
        if (d2 > rout * rout) { car_free(k, 0, now); continue; }            /* too far to be seen */
        key[i] = 0;                      /* this player has a car */

        {   /* where the player is by now: the last position heard, carried on at their
             * velocity for as long as nothing newer has come (0.35 s at most) */
            float gvx = s_ghosts.gvel[i][0], gvz = s_ghosts.gvel[i][1], ext;
            if (!isfinite(gvx) || !isfinite(gvz) || gvx * gvx + gvz * gvz > 200.0f * 200.0f) gvx = gvz = 0.0f;
            if (gh[i].x != s_car_tgt[k].x || gh[i].y != s_car_tgt[k].y || gh[i].z != s_car_tgt[k].z) {
                s_car_tgt[k].x = gh[i].x; s_car_tgt[k].y = gh[i].y; s_car_tgt[k].z = gh[i].z; s_car_tgt[k].t = now;
            }
            ext = now - s_car_tgt[k].t;
            if (!(ext > 0.0f)) ext = 0.0f;
            if (ext > 0.5f) ext = 0.5f;
            tx = gh[i].x + gvx * ext; ty = gh[i].y + s_ghosts.car_yoff; tz = gh[i].z + gvz * ext;
        }
        hl = sqrtf(gh[i].fx * gh[i].fx + gh[i].fz * gh[i].fz);
        hx = gh[i].fx / hl; hz = gh[i].fz / hl;
        dx = tx - c->x; dz = tz - c->z;
        if (dx * dx + dz * dz > 60.0f * 60.0f) {     /* the player jumped (respawn): no glide across town */
            c->x = tx; c->y = ty; c->z = tz; c->vx = c->vy = c->vz = 0.0f; c->hx = hx; c->hz = hz;
        } else if (dt > 0.0f) {          /* a critically damped spring towards the player, matching
                                          * their velocity too: a spring on position alone trails a
                                          * moving target by 2/w seconds (0.2 s, ~5 m at speed) */
            float gvx = s_ghosts.gvel[i][0], gvz = s_ghosts.gvel[i][1];
            if (!isfinite(gvx) || !isfinite(gvz) || gvx * gvx + gvz * gvz > 200.0f * 200.0f) gvx = gvz = 0.0f;
            a = w * w * (tx - c->x) + 2.0f * w * (gvx - c->vx); c->vx += a * dt; c->x += c->vx * dt;
            a = w * w * (ty - c->y) - 2.0f * w * c->vy;         c->vy += a * dt; c->y += c->vy * dt;
            a = w * w * (tz - c->z) + 2.0f * w * (gvz - c->vz); c->vz += a * dt; c->z += c->vz * dt;
            kh = 8.0f * dt; if (kh > 1.0f) kh = 1.0f;
            if (c->hx * hx + c->hz * hz < -0.5f) { c->hx = hx; c->hz = hz; }  /* turned right round: no spin */
            else {
                c->hx += (hx - c->hx) * kh; c->hz += (hz - c->hz) * kh;
                hl = sqrtf(c->hx * c->hx + c->hz * c->hz);
                if (hl > 1.0e-4f) { c->hx /= hl; c->hz /= hl; } else { c->hx = hx; c->hz = hz; }
            }
        }
        memcpy(s_car_prev[k], s_car_cur[k], sizeof s_car_cur[k]);
        car_matrix(s_car_cur[k], c);
        c->age++;
        car_write(c->veh, k);
        used++;
    }

    /* Crowd limit: car_max (the page's, from the frame rate) cars at most, and the nearest players
     * get them -- a car is handed from the farthest player to a nearer one only if that one is
     * 30 units nearer, so two players at about the same distance don't swap it back and forth. */
    lim = (s_ghosts.car_max >= 1u && s_ghosts.car_max <= MC3_CARS) ? (int)s_ghosts.car_max : MC3_CARS;
    {
        float need = 1.0e30f;
        for (i = 0; i < (int)n; i++)
            if (key[i]) {
                float dx = gh[i].x - px, dz = gh[i].z - pz, d2 = dx * dx + dz * dz;
                if (d2 < rin * rin && d2 < need) need = d2;
            }
        while (used > lim || (need < 1.0e29f && used >= lim)) {
            int far = -1;
            float fd = -1.0f;
            for (k = 0; k < MC3_CARS; k++) {
                struct mc3_car *c = &s_ghosts.car[k];
                float dx, dz, d2;
                if (!c->veh) continue;
                dx = c->x - px; dz = c->z - pz; d2 = dx * dx + dz * dz;
                if (d2 > fd) { fd = d2; far = k; }
            }
            if (far < 0) break;
            if (used <= lim) {               /* full: a handover, only to someone clearly nearer */
                if (sqrtf(fd) < sqrtf(need) + 30.0f) break;
                need = 1.0e30f;              /* one a frame */
            }
            car_free(far, 0, now);
            used--;
        }
    }

    for (i = 0; i < (int)n; i++) {       /* players near enough who have no car yet (nearest first: the page's order) */
        float dx, dz, hl;
        uint32_t veh;
        struct mc3_car *c;
        int wait = 0;
        if (!key[i]) continue;
        dx = gh[i].x - px; dz = gh[i].z - pz;
        if (dx * dx + dz * dz > rin * rin) continue;
        for (k = 0; k < MC3_CARS; k++)   /* just knocked off: not while the local car is still on the spot */
            if (s_car_cool[k].id == key[i] && s_car_cool[k].until > 0.0f) {
                if (now < s_car_cool[k].until || dx * dx + dz * dz < 12.0f * 12.0f) wait = 1;
                else { s_car_cool[k].id = 0; s_car_cool[k].until = 0.0f; }
            }
        if (wait) continue;
        for (k = 0; k < MC3_CARS; k++) if (!s_ghosts.car[k].veh) break;
        if (k == MC3_CARS || used >= lim) break;
        veh = car_pick(mgr, px, pz);
        if (!veh) break;
        { int sp = spare_of(veh); if (sp >= 0) s_spare[sp] = 0; }   /* a spare no more */
        c = &s_ghosts.car[k];
        hl = sqrtf(gh[i].fx * gh[i].fx + gh[i].fz * gh[i].fz);
        c->veh = veh; c->id = key[i]; c->type = MEM32(veh + 0x138u);
        c->x = gh[i].x; c->y = gh[i].y + s_ghosts.car_yoff; c->z = gh[i].z;
        c->hx = gh[i].fx / hl; c->hz = gh[i].fz / hl;
        c->vx = s_ghosts.gvel[i][0]; c->vz = s_ghosts.gvel[i][1]; c->vy = 0.0f;   /* already moving as its player is */
        if (!isfinite(c->vx) || !isfinite(c->vz) || c->vx * c->vx + c->vz * c->vz > 200.0f * 200.0f) c->vx = c->vz = 0.0f;
        s_car_tgt[k].x = gh[i].x; s_car_tgt[k].y = gh[i].y; s_car_tgt[k].z = gh[i].z; s_car_tgt[k].t = now;
        car_matrix(s_car_cur[k], c);
        memcpy(s_car_prev[k], s_car_cur[k], sizeof s_car_cur[k]);
        c->age = 1;
        car_write(veh, k);
        s_ghosts.car_claims++;
        used++;
    }
    s_ghosts.car_n = (uint32_t)used;
    rc_frame(mgr, now);
}

/* -- Online: empty streets ---------------------------------------------
 * The traffic manager keeps spawning cars until it has its target, [mgr + 0x68 .. 0x7C]
 * (one per time of day / mode; 48, 48, 48, 48, 40, 30 in San Diego), in sub_00067450.
 * Online that target is the borrowed cars plus two spares: the city only puts cars on
 * roads as they come into range, so the first two cars nobody drives are kept as spares,
 * out of sight (car_put_far), for the next player who comes near, and every other one is
 * taken off the street in its own update (sub_000730B0, as the game does with a car out
 * of everyone's range). Offline the saved targets go back. Traffic cannot simply be
 * switched off: with the game's "no traffic" option the pool does not exist at all. */
extern void sub_000730B0(void);
static uint32_t s_quiet_saved[6], s_quiet_mgr;

static void quiet_targets(void)
{
    uint32_t mgr = ghost_va_ok(MEM32(0x004CA64Cu)) ? MEM32(MEM32(0x004CA64Cu) + 8u) : 0;
    uint32_t want = 0, k, n = s_ghosts.n;
    float px = s_ghosts.self[0], pz = s_ghosts.self[2], rin = s_ghosts.car_rin;
    if (!ghost_va_ok(mgr) || MEM16(mgr + 0x12Cu) == 0 || !ghost_va_ok(MEM32(mgr + 0x130u)))
        return;
    if (mgr != s_quiet_mgr) {            /* a new city: its own targets */
        for (k = 0; k < 6; k++) s_quiet_saved[k] = MEM32(mgr + 0x68u + 4u * k);
        s_quiet_mgr = mgr;
    }
    if (!s_ghosts.quiet) {
        for (k = 0; k < 6; k++)
            if (MEM32(mgr + 0x68u + 4u * k) != s_quiet_saved[k]) MEM32(mgr + 0x68u + 4u * k) = s_quiet_saved[k];
        s_ghosts.quiet_target = s_quiet_saved[0];
        return;
    }
    if (!(rin > 10.0f)) rin = 300.0f;
    if (n > MC3_GHOSTS) n = MC3_GHOSTS;
    /* The city spawns whenever its target is above zero, whatever it counts: so the target
     * is zero unless a spare is missing or a nearby player has no car yet. Any car beyond
     * that is taken away again (sub_00079C30 below). */
    {
        uint32_t lacking = 0, spares = 0, c;
        if (s_ghosts.cars_on && s_ghosts.self[7] == 1.0f)
            for (k = 0; k < n; k++) {
                struct mc3_ghost gh = s_ghosts.g[k];
                float dx = gh.x - px, dz = gh.z - pz;
                uint32_t key = gh.on == 1u ? 0x80000000u + k : gh.on;
                if (!gh.on || !isfinite(dx) || !isfinite(dz) || dx * dx + dz * dz > rin * rin) continue;
                for (c = 0; c < MC3_CARS; c++)
                    if (s_ghosts.car[c].veh && s_ghosts.car[c].id == key) break;
                if (c == MC3_CARS) lacking++;
            }
        for (c = 0; c < CAR_SPARES; c++)
            if (s_spare[c] && car_live(mgr, s_spare[c]) && car_slot_of(s_spare[c]) < 0) spares++;
        want = (lacking || (s_ghosts.cars_on && spares < CAR_SPARES))
             ? s_ghosts.car_n + CAR_SPARES + lacking : 0u;
    }
    for (k = 0; k < 6; k++) MEM32(mgr + 0x68u + 4u * k) = want;
    s_ghosts.quiet_target = want;
}

/* sub_00079C30(mgr; car, dt), ret 8: one traffic car's update */
void sub_00079C30(void)
{
    uint32_t mgr = g_ecx, veh = MEM32(g_esp + 0x04u);
    float now = MEMF(CAR_TIME);
    int slot;

    if (now != s_car_last_time && (s_ghosts.n || s_ghosts.car_n) && ghost_va_ok(mgr) &&
        car_live(mgr, veh)) {            /* first car of a new frame, in the city's own pool */
        uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp;
        uint32_t eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        cars_frame(mgr, now);
        g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0;
        g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }

    /* A borrowed car drives its own rails at its own speed (+0xE0) -- only where it is drawn
     * is overwritten -- so its wheels turned at traffic speed even while its player stood
     * still (owner, 2026-11-11). Its speed is the player's (the spring's velocity), 0 when
     * stopped, before the game's update turns the wheels from it. */
    slot = car_slot_of(veh);
    if (slot >= 0 && s_ghosts.car[slot].age) {
        float vx = s_ghosts.car[slot].vx, vz = s_ghosts.car[slot].vz, sp = sqrtf(vx * vx + vz * vz);
        if (!(sp >= 0.3f) || sp > 200.0f) sp = 0.0f;
        MEMF(veh + 0xE0u) = sp;
    }

    sub_00079C30_gen();                  /* the game's own update; pops its arguments */

    slot = car_slot_of(veh);
    if (slot < 0 && s_ghosts.quiet && car_live(mgr, veh) && !MEM8(veh + 0xADu) && !MEM32(veh + 0xA8u)
        && MEM32(veh + 0xC4u) != 1u) {  /* online: a car nobody drives has no business on the street */
        uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp;
        uint32_t eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        int sp = spare_of(veh), j;
        if (sp < 0 && !MEM32(veh + 0x13Cu) && MEM32(veh + 0xFCu) && s_ghosts.cars_on)
            for (j = 0; j < CAR_SPARES; j++)  /* a free spare place (or one whose car is gone) */
                if (!s_spare[j] || !car_live(mgr, s_spare[j]) || car_slot_of(s_spare[j]) >= 0) {
                    s_spare[j] = veh; sp = j; break;
                }
        if (sp >= 0) {                   /* kept, out of sight and out of the way */
            car_put_far(veh);
            car_tell_level(veh);
        } else {
            g_ecx = veh;                 /* thiscall, no arguments, ret */
            PUSH32(g_esp, 0x0006504Bu);
            sub_000730B0();
            s_ghosts.quiet_removed++;
        }
        g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0;
        g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
        return;
    }
    if (slot >= 0 && s_ghosts.car[slot].age && !MEM32(veh + 0x13Cu) && MEM16(veh + 0x2Cu) != 0xFFFFu) {
        uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp;
        uint32_t eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        car_write(veh, slot);            /* back to where its player is */
        g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0;
        g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }
}

/* Pedestrians, online: none. The city's pedestrians (and traffic) are loaded once, for the
 * front end's backdrop, so they cannot be left out at load. Every frame sub_0001E5E0 tells
 * the pedestrian manager ([[0x50115C]]) where each viewer is, sub_00202F30(mgr; viewer index,
 * the viewer car's 3x4 matrix, ...) -> sub_0028EA90, which places the zones pedestrians
 * live in from that matrix at once (the matrix is not kept). Online the manager is given a
 * viewer far outside the city instead: the pedestrians around the player fall out of range
 * and are taken away, and none are made near any player. */
extern void sub_00202F30_gen(void);
void sub_00202F30(void)
{
    uint32_t sp0, ret, a1, a3, m;
    if (!s_ghosts.quiet) {
        sub_00202F30_gen();
        return;
    }
    sp0 = g_esp;
    ret = MEM32(sp0); a1 = MEM32(sp0 + 4u); a3 = MEM32(sp0 + 0xCu);
    g_esp -= 0x40u;                      /* the far viewer's matrix, on the guest stack */
    m = g_esp;
    MEMF(m + 0x00) = 1.0f; MEMF(m + 0x04) = 0.0f; MEMF(m + 0x08) = 0.0f;
    MEMF(m + 0x0C) = 0.0f; MEMF(m + 0x10) = 1.0f; MEMF(m + 0x14) = 0.0f;
    MEMF(m + 0x18) = 0.0f; MEMF(m + 0x1C) = 0.0f; MEMF(m + 0x20) = 1.0f;
    MEMF(m + 0x24) = 60000.0f; MEMF(m + 0x28) = -500.0f; MEMF(m + 0x2C) = 60000.0f;
    PUSH32(g_esp, a3);
    PUSH32(g_esp, m);
    PUSH32(g_esp, a1);
    PUSH32(g_esp, ret);
    sub_00202F30_gen();                  /* ret 0xC: pops the copy */
    g_esp = sp0 + 0x10u;                 /* and this call's own ret 0xC */
    s_ghosts.peds_far++;
}

/* sub_00203C80 (no arguments): at city load, loads the pedestrians when [[0x507B20] +
 * 0x108] (the Pedestrians option) is set -- otherwise it takes the game's own "no peds"
 * path (the manager object is still made, nothing is loaded). Online, it is told the
 * option is off for the length of the call. */
extern void sub_00203C80_gen(void);
void sub_00203C80(void)
{
    uint32_t g = MEM32(0x00507B20u);
    uint8_t was = 0;
    int quiet = s_ghosts.quiet && ghost_va_ok(g);
    if (quiet) { was = MEM8(g + 0x108u); MEM8(g + 0x108u) = 0; s_ghosts.peds_skipped++; }
    sub_00203C80_gen();
    fprintf(stderr, "[GHOST] city load: pedestrians %s (option %u, manager %08X)\n",
            quiet ? "skipped (online)" : "as the game says", ghost_va_ok(g) ? MEM8(g + 0x108u) : 0u,
            ghost_va_ok(MEM32(0x0050115Cu)) ? MEM32(MEM32(0x0050115Cu)) : 0u);
    if (quiet) MEM8(g + 0x108u) = was;
}

/* sub_00079B40(mgr; car), ret 4, returns al: takes a car whose road position is out of
 * every viewer's range out of the world. A borrowed car stays, and so does a spare (the
 * city only makes new cars where roads come into range, so a lost spare can mean a player
 * who arrives while nobody moves gets no car). */
void sub_00079B40(void)
{
    uint32_t veh = MEM32(g_esp + 0x04u);
    if (car_slot_of(veh) >= 0 || (s_ghosts.quiet && spare_of(veh) >= 0)) {
        g_eax &= 0xFFFFFF00u;            /* al = 0: nothing removed */
        g_esp += 8;                      /* ret 4 */
        return;
    }
    sub_00079B40_gen();
}

/* -- The same model for a player on every screen -----------------------------------
 * A borrowed traffic car is whatever model the city made, so one player looked different on
 * every screen. Each loaded traffic type has a name ([type+0xC], e.g. "va_civic_sh"); the
 * loaded types are [[mgr+0x30] + i*4], i < (u16)[mgr+0x34], one fixed set per city and time
 * of day (tune/traffic/<city>/<city>_<tod>.density), so the same on every client in the same
 * city. A player's model: their id hashed over those names, sorted, leaving out trucks
 * with trailers (kind [type+0x294] == 6) and anything longer than a car (half length
 * [type+0x298] > 2.4). The car's type cannot simply be changed: spawning and despawning
 * file the car under its type ([type+0x5C]) and its road link counts its type's length.
 * So it is changed only while the car is drawn -- the drawable's draw, sub_0006DFB0 (thiscall,
 * ecx = car + 0x10, vtable 0x416D24 [0x10]), reads the model from [car+0x138] (and +0x20,
 * the variant byte +0xB5) -- and put back right after. Nothing else sees it. */
extern void sub_0006DFB0_gen(void);
static uint32_t s_model_mgr, s_model_n, s_model_types[64], s_model_arr, s_model_cnt;

static int model_name_cmp(uint32_t a, uint32_t b)       /* strcmp of two guest C strings */
{
    uint32_t k;
    if (!ghost_va_ok(a) || !ghost_va_ok(b)) return (int)(a > b) - (int)(a < b);
    for (k = 0; k < 64; k++) {
        uint8_t x = MEM8(a + k), y = MEM8(b + k);
        if (x != y) return (int)x - (int)y;
        if (!x) return 0;
    }
    return 0;
}

static void model_list(uint32_t mgr)                    /* the car types, by name */
{
    uint32_t arr, n, i, j;
    s_model_mgr = mgr; s_model_n = 0; s_model_arr = 0; s_model_cnt = 0;
    if (!ghost_va_ok(mgr)) return;
    arr = MEM32(mgr + 0x30u); n = MEM16(mgr + 0x34u);
    s_model_arr = arr; s_model_cnt = n;
    if (!ghost_va_ok(arr) || n > 256) return;
    for (i = 0; i < n && s_model_n < 64; i++) {
        uint32_t ty = MEM32(arr + 4u * i);
        if (!ghost_va_ok(ty) || !ghost_va_ok(MEM32(ty + 0xCu))) continue;
        if (MEM32(ty + 0x294u) == 6u || !(MEMF(ty + 0x298u) > 0.5f) || MEMF(ty + 0x298u) > 2.4f) continue;
        for (j = s_model_n; j > 0 && model_name_cmp(MEM32(s_model_types[j - 1] + 0xCu), MEM32(ty + 0xCu)) > 0; j--)
            s_model_types[j] = s_model_types[j - 1];
        s_model_types[j] = ty; s_model_n++;
    }
}

static uint32_t model_hash(uint32_t h)
{
    h ^= h >> 16; h *= 0x7FEB352Du; h ^= h >> 15; h *= 0x846CA68Bu; h ^= h >> 16;
    return h;
}

/* What kind of vehicle a traffic type is, from its name ([type+0xC], e.g. va_tacoma_sh):
 * 2 truck/SUV, 3 van, else 1 car -- to match the kind of car a player chose (gclass). */
static uint32_t model_kind(uint32_t ty)
{
    static const char *const truck[] = { "tacoma", "truck", "pickup", "silverado", "f150", "ram", "suv",
                                         "tahoe", "explorer", "escalade", "hummer", "h1", "h2", 0 };
    static const char *const van[] = { "odessey", "odyssey", "van", "caravan", "bus", 0 };
    char s[40]; uint32_t p = MEM32(ty + 0xCu), k;
    int i;
    if (!ghost_va_ok(p)) return 1;
    for (k = 0; k < sizeof s - 1; k++) { char c = (char)MEM8(p + k); if (!c) break; s[k] = (char)(c >= 'A' && c <= 'Z' ? c + 32 : c); }
    s[k] = 0;
    for (i = 0; truck[i]; i++) if (strstr(s, truck[i])) return 2;
    for (i = 0; van[i]; i++) if (strstr(s, van[i])) return 3;
    return 1;
}

static uint32_t model_for(uint32_t id, uint32_t kind)
{
    uint32_t h = id, pick[64], np = 0, i;
    uint32_t mgr = ghost_va_ok(MEM32(0x004CA64Cu)) ? MEM32(MEM32(0x004CA64Cu) + 8u) : 0;
    /* the city can be torn down and rebuilt at the same address (restart, a new vehicle, the
     * garage): list the types again whenever the manager's type array is not what it was */
    if (mgr != s_model_mgr || !s_model_n || !ghost_va_ok(mgr) || MEM32(mgr + 0x30u) != s_model_arr
        || MEM16(mgr + 0x34u) != s_model_cnt) model_list(mgr);
    if (!s_model_n) return 0;
    h ^= h >> 16; h *= 0x7FEB352Du; h ^= h >> 15; h *= 0x846CA68Bu; h ^= h >> 16;
    /* the kind of car the player chose, when the city has one (owner, 2026-11-11: "showing
     * random vehicles"); the id still picks among them, the same on every screen */
    if (kind) for (i = 0; i < s_model_n && np < 64; i++) if (model_kind(s_model_types[i]) == kind) pick[np++] = s_model_types[i];
    if (np) return pick[h % np];
    return s_model_types[h % s_model_n];
}

/* the chosen-car kind the page wrote for the player with this id (0: unknown) */
static uint32_t ghost_kind(uint32_t id)
{
    uint32_t n = s_ghosts.n, i;
    if (n > MC3_GHOSTS) n = MC3_GHOSTS;
    for (i = 0; i < n; i++) {
        uint32_t key = s_ghosts.g[i].on == 1u ? 0x80000000u + i : s_ghosts.g[i].on;
        if (key == id) return s_ghosts.gclass[i] <= 3u ? s_ghosts.gclass[i] : 0u;
    }
    return 0;
}

void sub_0006DFB0(void)
{
    uint32_t veh = g_ecx - 0x10u, want = 0, t138 = 0, t20 = 0;
    uint8_t b5 = 0, c16c = 0;
    int slot = car_slot_of(veh);
    if (slot >= 0) s_ghosts.car_drawn[slot] = s_ghosts.car_frames;   /* drawn this frame: not culled */
    if (slot >= 0 && s_ghosts.car[slot].age && s_ghosts.cars_same_model)
        want = model_for(s_ghosts.car[slot].id, ghost_kind(s_ghosts.car[slot].id));
    if (want) {                          /* only a type the city has right now, and a car of its pool */
        uint32_t mgr = MEM32(MEM32(0x004CA64Cu) + 8u), arr = MEM32(mgr + 0x30u), n = MEM16(mgr + 0x34u), k;
        if (!car_live(mgr, veh) || !ghost_va_ok(arr) || n > 256) want = 0;
        else { for (k = 0; k < n && MEM32(arr + 4u * k) != want; k++) ; if (k == n) want = 0; }
    }
    if (want && want != MEM32(veh + 0x138u)) {
        t138 = MEM32(veh + 0x138u); t20 = MEM32(veh + 0x20u); b5 = MEM8(veh + 0xB5u); c16c = MEM8(veh + 0x16Cu);
        MEM32(veh + 0x138u) = want; MEM32(veh + 0x20u) = want; MEM8(veh + 0xB5u) = 0;
        /* the paint: the spawner rolls a colour slot 0..7 into +0x16C (sub_0006F9A0); here it
         * comes from the player's id too, so the colour matches on every screen as well */
        MEM8(veh + 0x16Cu) = (uint8_t)((model_hash(s_ghosts.car[slot].id ^ 0x5bd1e995u) >> 8) & 7u);
        s_ghosts.car[slot].type = want;
    } else want = 0;
    sub_0006DFB0_gen();                  /* the game's own draw; pops its argument */
    if (want) { MEM32(veh + 0x138u) = t138; MEM32(veh + 0x20u) = t20; MEM8(veh + 0xB5u) = b5; MEM8(veh + 0x16Cu) = c16c; }
}

/* ── Real cars, stage 1: build a car the way the game builds a player's, and draw it ────────
 *
 * mc3-player-cars-re.md. The player constructor (sub_00292150) builds its vehicle with a
 * factory object on its stack: sub_0029C6D0(this; name, 0, slot, record, flag, controller)
 * (ret 0x18), sub_0029D090(this) -> the vehicle (VEH), sub_0029C720(this) its destructor; the
 * record is [[0x507B20] + 0x11C + slot * 0x2C] and the name the record's +0xE3. Here: the local
 * player's own record and name (its model is loaded: nothing to read from the disc), slot 7, no
 * controller. The factory registers the vehicle for physics and the per-frame driving update;
 * the game's own park (sub_000EC950(VEH): out of the physics level and the update, car hidden)
 * takes it out of both, and sub_000885C0(car + 8, 1) links the car to its model's draw list
 * again. Then its draw matrix (car + 0xA0, position + 0xC4) is ours: the local car's, moved
 * pc_side units to its right, every frame -- a car of your model beside you, following you.
 * pc_req 1 builds it, 2 parks it for good. Stage 2 drives it from a player's positions. */
extern void sub_0029C6D0(void);
extern void sub_0029D090(void);
extern void sub_0029CF30(void);
extern void sub_0029C720(void);
extern void sub_000EC950(void);
extern void sub_000885C0(void);
extern void sub_000E6D60(void);
extern void sub_000EA070(void);

/* Why the built car isn't drawn (static reading, 2026-11-11): a drawable instance (car + 8) links
 * into its model's instance list (model = [inst + 0x10], list head model + 0x1C, inst +4 prev /
 * +8 next; sub_00088860), and a model with instances links into its dictionary's active list
 * (dictionary = [model + 8], vtable 0x4176C4; active head dict + 0xC, model +0x14 prev / +0x18
 * next). A dictionary draws only its active models (sub_00088390 -> model vtbl+8 sub_00088760 ->
 * each instance's vtbl+0x10). Registry: dict + 8 head, model + 0x10 next, model + 0xC name
 * (sub_00088310 add, sub_00088330 remove, sub_000882B0 find). Built with the showroom's
 * dictionaries the model sits in the garage's dictionary, which the city never draws. pc_swap
 * bit 8: move it (and its active link) into the dictionary of the local car's model. */
static int pc_dict_ok(uint32_t d) { return ghost_va_ok(d) && MEM32(d) == 0x004176C4u; }
static void pc_move_model(void)
{
    uint32_t inst, m, d, lcar, lm, dc, n = 0, a = 0, x;
    if (!(s_ghosts.pc_swap & 8u) || !ghost_va_ok(s_pc_player) || !ghost_va_ok(MEM32(s_pc_player + 0x14u))) return;
    lcar = MEM32(MEM32(s_pc_player + 0x14u) + 0xCu);
    inst = s_ghosts.pc_car + 8u;
    m = MEM32(inst + 0x10u);
    lm = ghost_va_ok(lcar) ? MEM32(lcar + 8u + 0x10u) : 0;
    if (!ghost_va_ok(m) || !ghost_va_ok(lm)) { fprintf(stderr, "[REALCAR] move: model %08X local %08X -- no\n", m, lm); return; }
    d = MEM32(m + 8u); dc = MEM32(lm + 8u);
    for (x = ghost_va_ok(d) ? MEM32(d + 8u) : 0; ghost_va_ok(x) && n < 4096u; x = MEM32(x + 0x10u)) n++;
    for (x = ghost_va_ok(d) ? MEM32(d + 0xCu) : 0; ghost_va_ok(x) && a < 4096u; x = MEM32(x + 0x18u)) a++;
    fprintf(stderr, "[REALCAR] move: model %08X (vt %08X, inst head %08X) dict %08X (vt %08X, %u models, %u active)"
            " -> local model %08X dict %08X (vt %08X); swap dicts %08X %08X %08X\n",
            m, MEM32(m), MEM32(m + 0x1Cu), d, ghost_va_ok(d) ? MEM32(d) : 0, n, a, lm, dc, ghost_va_ok(dc) ? MEM32(dc) : 0,
            MEM32(MEM32(0x4F3930u) + 0x14u), MEM32(MEM32(0x4F3930u) + 0x18u), MEM32(MEM32(0x4F3930u) + 0x1Cu));
    if (d == dc || !pc_dict_ok(d) || !pc_dict_ok(dc)) return;
    /* out of the garage's active list (sub_00088790's steps) */
    if (MEM32(m + 0x14u) || MEM32(m + 0x18u) || MEM32(d + 0xCu) == m) {
        uint32_t p = MEM32(m + 0x14u), q = MEM32(m + 0x18u);
        if (p) MEM32(p + 0x18u) = q; else MEM32(d + 0xCu) = q;
        if (q) MEM32(q + 0x14u) = p;
        MEM32(m + 0x14u) = 0; MEM32(m + 0x18u) = 0;
    }
    /* out of its registry chain (sub_00088330), into the city's (sub_00088310) */
    if (MEM32(d + 8u) == m) MEM32(d + 8u) = MEM32(m + 0x10u);
    else for (x = MEM32(d + 8u); ghost_va_ok(x); x = MEM32(x + 0x10u))
        if (MEM32(x + 0x10u) == m) { MEM32(x + 0x10u) = MEM32(m + 0x10u); break; }
    MEM32(m + 0x10u) = MEM32(dc + 8u); MEM32(m + 8u) = dc; MEM32(dc + 8u) = m;
    /* active in the city's dictionary while it has instances (sub_00088860's steps) */
    if (MEM32(m + 0x1Cu)) {
        uint32_t h = MEM32(dc + 0xCu);
        MEM32(m + 0x14u) = 0; MEM32(m + 0x18u) = h;
        if (h) MEM32(h + 0x14u) = m;
        MEM32(dc + 0xCu) = m;
    }
    fprintf(stderr, "[REALCAR] move: model %08X now in dict %08X%s\n", m, dc, MEM32(m + 0x1Cu) ? ", active" : " (no instances)");
}

static uint32_t s_rcb_veh, s_rcb_car, s_rcb_cfg;   /* what rc_build_rec built (+ its config, factory +0x4C) */
static uint32_t rc_build_rec(uint32_t record)
{
    uint32_t fac, veh = 0;
    uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
    s_rcb_veh = s_rcb_car = s_rcb_cfg = 0;
    if (!ghost_va_ok(record)) return 0xE2u;
    fac = (g_esp - 0x600u) & ~0xFu;      /* the factory object, on this thread's stack like the game's */
    g_esp = fac - 0x20u;
    /* as the showroom (sub_00125560) builds a car at runtime: (name, 0, slot 0, record, 1,
     * controller 0), its texture dictionaries for the build, and its build step sub_0029CF30 */
    PUSH32(g_esp, 0u);                   /* controller 0, as the showroom */
    PUSH32(g_esp, 1u);                   /* flag (setup entry +0x18 set) */
    PUSH32(g_esp, record);
    PUSH32(g_esp, s_ghosts.pc_slot);     /* slot: 0 as the showroom (pc_slot to try others) */
    PUSH32(g_esp, 0u);
    PUSH32(g_esp, record + 0xE3u);       /* the car's name, as the record has it */
    PUSH32(g_esp, 0x00292341u);
    g_ecx = fac; sub_0029C6D0();
    {   /* what the factory's setup kept (expected: +4 name copy, +0x54 record, +0xE8 slot, +0xEC controller) */
        char nm[20]; uint32_t k;
        for (k = 0; k < sizeof nm - 1; k++) { char c = (char)MEM8(fac + 4u + k); if (!c) break; nm[k] = (c >= 32 && c < 127) ? c : '?'; }
        nm[k] = 0;
        fprintf(stderr, "[REALCAR] factory after setup: vtbl %08X name '%s' +54 %08X +E8 %08X +EC %08X\n",
                MEM32(fac), nm, MEM32(fac + 0x54u), MEM32(fac + 0xE8u), MEM32(fac + 0xECu));
    }
    {   /* the showroom's texture dictionaries ([0x4F3930] +0x14/+0x18/+0x1C) for the build, the
         * city's put back after -- loading the car into the city's own dictionary blacked out its
         * textures (stage 1, second try). Only if they exist here (they belong to the garage). */
        uint32_t ctx = MEM32(0x4F3930u), d0 = 0, d1 = 0, d2 = 0, s0, s1, s2;
        int swap = 0;
        if (ghost_va_ok(ctx)) { d0 = MEM32(ctx + 0x14u); d1 = MEM32(ctx + 0x18u); d2 = MEM32(ctx + 0x1Cu); }
        swap = ghost_va_ok(d0) && ghost_va_ok(d1) && ghost_va_ok(d2);
        fprintf(stderr, "[REALCAR] dictionaries: ctx %08X -> %08X %08X %08X (city %08X %08X %08X)%s\n",
                ctx, d0, d1, d2, MEM32(0x4D0780u), MEM32(0x4D08D8u), MEM32(0x4D09F8u), swap ? "" : " -- not usable: no build");
        if (!swap) {
            g_esp = fac - 0x20u; PUSH32(g_esp, 0x002923C3u); g_ecx = fac; sub_0029C720();
            g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
            return 0xE5u;
        }
        s0 = MEM32(0x4D0780u); s1 = MEM32(0x4D08D8u); s2 = MEM32(0x4D09F8u);
        {   uint32_t m = s_ghosts.pc_swap & 7u ? s_ghosts.pc_swap & 7u : 7u;
            fprintf(stderr, "[REALCAR] swapping %s%s%s\n", m & 1u ? "0x4D0780 " : "", m & 2u ? "0x4D08D8 " : "", m & 4u ? "0x4D09F8" : "");
            if (m & 1u) { MEM32(0x4D0780u) = d0; MEM32(0x4D078Cu) = s0; }
            if (m & 2u) { MEM32(0x4D08D8u) = d1; MEM32(0x4D08DCu) = s1; }
            if (m & 4u) { MEM32(0x4D09F8u) = d2; MEM32(0x4D09E4u) = s2; } }
        g_esp = fac - 0x20u;
        PUSH32(g_esp, 0x001255EEu);
        g_ecx = fac; sub_0029CF30();
        MEM32(0x4D0780u) = s0; MEM32(0x4D078Cu) = 0;
        MEM32(0x4D08D8u) = s1; MEM32(0x4D08DCu) = 0;
        MEM32(0x4D09F8u) = s2; MEM32(0x4D09E4u) = 0;
    }
    fprintf(stderr, "[REALCAR] factory after build: eax %08X +44 %08X +48 %08X +4C %08X +50 %08X +E0 %02X\n",
            g_eax, MEM32(fac + 0x44u), MEM32(fac + 0x48u), MEM32(fac + 0x4Cu), MEM32(fac + 0x50u), MEM8(fac + 0xE0u));
    /* it returns the vehicle through a tail call to sub_0032CE70 (eax = [this + 0x44]), which
     * doesn't reach a C caller's g_eax: read it where that returns it from (first try, E3) */
    veh = ghost_va_ok(g_eax) ? g_eax : MEM32(fac + 0x44u);
    s_rcb_cfg = MEM32(fac + 0x4Cu);   /* registered with [0x4D31CC] by sub_000F2000; the player keeps it at +0x10 */
    g_esp = fac - 0x20u;
    PUSH32(g_esp, 0x002923C3u);
    g_ecx = fac; sub_0029C720();
    g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    if (!ghost_va_ok(veh)) return 0xE3u;
    s_rcb_veh = veh;
    MEM8(veh + 0x5Eu) = 1;               /* AI: not the local player's car (slot 0 with 0 here: 30 -> 3.7 fps) */
    s_rcb_car = MEM32(veh + 0xCu);
    if (!ghost_va_ok(s_rcb_car)) return 0xE4u;
    /* out of the physics and the driving update, then drawn again */
    PUSH32(g_esp, 0x00291690u);
    g_ecx = veh; sub_000EC950();
    g_esp = esp0;
    PUSH32(g_esp, 1u);
    PUSH32(g_esp, 0x000EC9A0u);
    g_ecx = s_rcb_car + 8u; sub_000885C0();
    g_esp = esp0;
    g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    return 1u;
}

static uint32_t s_pc_cfg;
static uint32_t pc_build(void)
{
    uint32_t setup = MEM32(0x507B20u), slot, r;
    if (!ghost_va_ok(setup)) return 0xE1u;
    slot = MEM32(setup + 0x3D4u);
    if (slot > 7u) slot = 0;
    r = rc_build_rec(MEM32(setup + 0x11Cu + slot * 0x2Cu));
    s_ghosts.pc_veh = s_rcb_veh; s_ghosts.pc_car = s_rcb_car; s_pc_cfg = s_rcb_cfg;
    if (r == 1u) pc_move_model();
    return r;
}

/* pc_req 3: the factory's first steps one by one, nothing built -- the name in the record, its
 * index from sub_002426E0 (cdecl, the name), the "loaded" check sub_00241F10 (thiscall on the car
 * table entry [0x51885C] + index * 0x1C) and an allocation of the vehicle data's size with the
 * game's allocator sub_00198790 (cdecl; leaked, a test) -- logged as [REALCAR] probe. */
extern void sub_002426E0(void);
extern void sub_00241F10(void);
extern void sub_00198790(void);
static void pc_probe(void)
{
    uint32_t setup = MEM32(0x507B20u), slot, record, name, idx = 0xFFFFFFFFu, entry = 0, loaded = 0, mem = 0, k;
    uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
    char nm[24];
    if (!ghost_va_ok(setup)) { fprintf(stderr, "[REALCAR] probe: no setup\n"); return; }
    slot = MEM32(setup + 0x3D4u); if (slot > 7u) slot = 0;
    record = MEM32(setup + 0x11Cu + slot * 0x2Cu);
    if (!ghost_va_ok(record)) { fprintf(stderr, "[REALCAR] probe: slot %u record %08X bad\n", slot, record); return; }
    name = record + 0xE3u;
    for (k = 0; k < sizeof nm - 1; k++) { char c = (char)MEM8(name + k); if (!c) break; nm[k] = (c >= 32 && c < 127) ? c : '?'; }
    nm[k] = 0;
    PUSH32(g_esp, name); PUSH32(g_esp, 0x0029D0A6u);
    sub_002426E0();
    idx = g_eax; g_esp = esp0;
    if (idx < 0x400u && ghost_va_ok(MEM32(0x51885Cu))) {
        entry = MEM32(0x51885Cu) + idx * 0x1Cu;
        PUSH32(g_esp, 0x0029D0BBu);
        g_ecx = entry; sub_00241F10();
        loaded = g_eax & 0xFFu; g_esp = esp0;
    }
    PUSH32(g_esp, 0x2118u); PUSH32(g_esp, 0x0029D0CBu);
    sub_00198790();
    mem = g_eax; g_esp = esp0;
    g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    s_ghosts.pc_veh = idx; s_ghosts.pc_car = mem; s_ghosts.pc_state = 0x30u | (loaded ? 1u : 0u);
    fprintf(stderr, "[REALCAR] probe: slot %u record %08X name '%s' -> index %d (table %08X, count %u), loaded %u, alloc(0x2118) %08X\n",
            slot, record, nm, (int)idx, MEM32(0x51885Cu), (unsigned)MEM16(0x518860u), loaded, mem);
}

/* once per frame (from cars_frame): build on request, then keep it beside the local car */
/* ── Teleport: the local car put down at a place (a friend's "join") ─────────────────────────
 * Tested live (2026-11-11): the car's position lives in several copies -- its physics object
 * [sim + 0x68] (sim = VEH+8) at +0x3C and +0x110, the sim's own at +0x80 and +0x170, and the
 * matrix holder [VEH+0x1C] +0x34 (what the vehicle manager copies to the drawn car+0xC4). Moving
 * them all by the same amount puts the car there for good (the holder alone was written back by
 * the physics the next step); the city streams the new place in a moment later. The physics
 * level is told after (level->vtbl[0x20](handle), as car_tell_level), which files the car in its
 * new grid cell. The car is turned to tp_hx/hz (if given) and stopped. */
static void tp_frame(void)
{
    uint32_t veh, hold, car, sim, phys, lvl, handle, k;
    float dx, dy, dz;
    static const uint32_t at_phys[2] = { 0x3Cu, 0x110u }, at_sim[2] = { 0x80u, 0x170u };
    if (s_ghosts.tp_req != 1u) return;
    s_ghosts.tp_req = 0;
    if (!ghost_va_ok(s_pc_player) || !ghost_va_ok(veh = MEM32(s_pc_player + 0x14u))) { s_ghosts.tp_state = 0xE1u; return; }
    hold = MEM32(veh + 0x1Cu); car = MEM32(veh + 0xCu); sim = MEM32(veh + 8u);
    phys = ghost_va_ok(sim) ? MEM32(sim + 0x68u) : 0;
    if (!ghost_va_ok(hold) || !ghost_va_ok(car) || !ghost_va_ok(phys)) { s_ghosts.tp_state = 0xE2u; return; }
    if (!isfinite(s_ghosts.tp_x) || !isfinite(s_ghosts.tp_y) || !isfinite(s_ghosts.tp_z)) { s_ghosts.tp_state = 0xE3u; return; }
    /* the copies must agree with the holder now, or this isn't the layout it was tested on */
    for (k = 0; k < 2; k++)
        if (fabsf(MEMF(phys + at_phys[k]) - MEMF(hold + 0x34u)) > 5.0f || fabsf(MEMF(phys + at_phys[k] + 8u) - MEMF(hold + 0x3Cu)) > 5.0f)
            { s_ghosts.tp_state = 0xE6u; fprintf(stderr, "[TELEPORT] physics copy +%X doesn't match: not moved\n", at_phys[k]); return; }
    dx = s_ghosts.tp_x - MEMF(hold + 0x34u);
    dy = s_ghosts.tp_y - MEMF(hold + 0x38u);
    dz = s_ghosts.tp_z - MEMF(hold + 0x3Cu);
    fprintf(stderr, "[TELEPORT] from %.1f %.1f %.1f to %.1f %.1f %.1f\n",
            MEMF(hold + 0x34u), MEMF(hold + 0x38u), MEMF(hold + 0x3Cu), s_ghosts.tp_x, s_ghosts.tp_y, s_ghosts.tp_z);
    for (k = 0; k < 2; k++) {
        MEMF(phys + at_phys[k]) += dx; MEMF(phys + at_phys[k] + 4u) += dy; MEMF(phys + at_phys[k] + 8u) += dz;
        MEMF(sim + at_sim[k]) += dx;   MEMF(sim + at_sim[k] + 4u) += dy;   MEMF(sim + at_sim[k] + 8u) += dz;
    }
    MEMF(hold + 0x34u) += dx; MEMF(hold + 0x38u) += dy; MEMF(hold + 0x3Cu) += dz;
    MEMF(car + 0xC4u) += dx;  MEMF(car + 0xC8u) += dy;  MEMF(car + 0xCCu) += dz;
    /* facing the way asked (tp_hx/hz: a forward row, out of the back), level: the rotation rows of
     * the physics matrix (phys +0x18), the holder's (+0x10) and the drawn one (car +0xA0) */
    {
        float hl = sqrtf(s_ghosts.tp_hx * s_ghosts.tp_hx + s_ghosts.tp_hz * s_ghosts.tp_hz), rot[9];
        if (hl > 1.0e-3f && isfinite(hl)) {
            float hx = s_ghosts.tp_hx / hl, hz = s_ghosts.tp_hz / hl;
            rot[0] = hz; rot[1] = 0.0f; rot[2] = -hx;       /* right */
            rot[3] = 0.0f; rot[4] = 1.0f; rot[5] = 0.0f;    /* up */
            rot[6] = hx; rot[7] = 0.0f; rot[8] = hz;        /* forward (out of the back) */
            for (k = 0; k < 9; k++) {
                MEMF(phys + 0x18u + 4u * k) = rot[k];
                MEMF(phys + 0xECu + 4u * k) = rot[k];      /* its second matrix (position +0x110): without it the turn is undone */
                MEMF(hold + 0x10u + 4u * k) = rot[k];
                MEMF(car + 0xA0u + 4u * k) = rot[k];
            }
        }
    }
    /* standing still: the physics' velocity (+0x48) and spin (+0x54) -- tested: +0x48 followed the
     * car's speed along its heading */
    for (k = 0; k < 6; k++) MEMF(phys + 0x48u + 4u * k) = 0.0f;
    lvl = MEM32(0x00518B78u); handle = MEM16(hold + 8u);
    s_ghosts.tp_state = 1u;
    if (handle != 0xFFFFu && ghost_va_ok(lvl) && MEM32(lvl)) {
        uint32_t sp0 = g_esp, ecx0 = g_ecx, eax0 = g_eax, edx0 = g_edx, target = MEM32(MEM32(lvl) + 0x20u);
        recomp_func_t fn = recomp_lookup_manual(target);
        if (!fn) fn = recomp_lookup(target);
        if (fn) { PUSH32(g_esp, handle); g_ecx = lvl; PUSH32(g_esp, 0x000722F7u); fn(); }
        g_esp = sp0; g_ecx = ecx0; g_eax = eax0; g_edx = edx0;
    }
}

static void pc_frame(void)
{
    uint32_t veh, car, lcar, k;
    float side, rx, ry, rz;
    if (s_ghosts.pc_req == 3u) { s_ghosts.pc_req = 0; pc_probe(); return; }
    if (s_ghosts.pc_req == 1u) {                              /* a new car each time (tests) */
        s_ghosts.pc_req = 0;
        s_ghosts.pc_state = pc_build();
        fprintf(stderr, "[REALCAR] build: state %X, vehicle %08X, car %08X\n",
                s_ghosts.pc_state, s_ghosts.pc_veh, s_ghosts.pc_car);
    }
    if (s_ghosts.pc_req == 2u && s_ghosts.pc_car) {           /* away: hidden, kept (not freed yet) */
        uint32_t esp0 = g_esp, ecx0 = g_ecx;
        s_ghosts.pc_req = 0;
        PUSH32(g_esp, 0u); PUSH32(g_esp, 0x000EC9A0u);
        g_ecx = s_ghosts.pc_car + 8u; sub_000885C0();
        g_esp = esp0; g_ecx = ecx0;
        s_ghosts.pc_state = 2u;
    }
    if (s_ghosts.pc_state != 1u) return;
    veh = s_ghosts.pc_veh; car = s_ghosts.pc_car;
    if (!ghost_va_ok(s_pc_player) || !ghost_va_ok(MEM32(s_pc_player + 0x14u))) return;
    lcar = MEM32(MEM32(s_pc_player + 0x14u) + 0xCu);
    if (!ghost_va_ok(lcar) || !ghost_va_ok(car) || lcar == car) return;
    side = s_ghosts.pc_side > 0.0f ? s_ghosts.pc_side : 4.0f;
    for (k = 0; k < 12; k++) MEMF(car + 0xA0u + 4u * k) = MEMF(lcar + 0xA0u + 4u * k);
    rx = MEMF(lcar + 0xA0u); ry = MEMF(lcar + 0xA4u); rz = MEMF(lcar + 0xA8u);   /* its right row */
    MEMF(car + 0xC4u) += rx * side; MEMF(car + 0xC8u) += ry * side; MEMF(car + 0xCCu) += rz * side;
    if (s_ghosts.pc_swap & 16u) {
        /* what the vehicle manager's update (sub_000EBF20) does for each car after copying its
         * matrix, and a parked car misses: sub_000E6D60(car; [VEH + 0x64]) and car vtbl+8
         * (sub_000EA070, the visual pose) */
        uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
        PUSH32(g_esp, MEM32(veh + 0x64u)); PUSH32(g_esp, 0x000EBFCCu);
        g_ecx = car; sub_000E6D60();
        g_esp = esp0;
        PUSH32(g_esp, 0x000EBFD3u);
        g_ecx = car; sub_000EA070();
        g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    }
}

/* ── Real cars, stage 2: each player with a car slot drawn in a real car of the model they chose ──
 *
 * The slots above still decide who gets a car, where it is (the spring) and the crowd limit;
 * each slot then gets a real car built as in stage 1 (rc_build_rec) from a copy of the local
 * player's record with the player's car name (gname, from the page) at +0xE3, kept in a pool and
 * reused for the next player of the same model (nothing is freed: the game's own teardown of a
 * vehicle isn't known yet). While a slot's real car shows, its borrowed traffic car is kept far
 * below the city. Builds: at most one each half second (one costs a frame or two); a name the
 * game doesn't know (sub_002426E0 = -1) or a failed build is not tried again. A new level
 * (another player object, traffic manager or loading-screen run) forgets the pool without
 * touching it: the level's teardown took those cars with it. */
#define RC_POOL 10
#define RC_ROOM_LOADED (1024 * 1024)       /* heap free needed to build a model already loaded */
#define RC_ROOM_NEW    (6400 * 1024)       /* ... and one still on the disc: always room left for a garage trip (~3.6 MB
                                              * more into the same heap while the city stays). 64 MB guest: 6.9 MB free
                                              * in San Diego, so one; 128 MB guest (108 MB heap): ~62 MB free, all 8 slots */
static int32_t  s_rc_room;
static struct { uint32_t veh, car, cfg; int slot; char name[16]; uint32_t look, owner; } s_rc[RC_POOL];   /* look: their record's hash; owner: whose it was */
static char     s_rc_bad[16][16];
static int      s_rc_badn;
static float    s_rc_next;
static uint32_t s_rc_key[3];

static void rc_show(uint32_t car, uint32_t on)
{
    uint32_t esp0 = g_esp, ecx0 = g_ecx, eax0 = g_eax, edx0 = g_edx;
    PUSH32(g_esp, on); PUSH32(g_esp, 0x000EC9A0u);
    g_ecx = car + 8u; sub_000885C0();
    g_esp = esp0; g_ecx = ecx0; g_eax = eax0; g_edx = edx0;
}

static int rc_valid(int r)
{
    uint32_t car = s_rc[r].car, veh = s_rc[r].veh;
    return ghost_va_ok(car) && ghost_va_ok(veh) && MEM32(veh + 0xCu) == car &&
           MEM32(car) == 0x0041E67Cu && MEM32(car + 8u) == 0x0041E664u;
}

/* the pose calls the vehicle manager makes for each car (stage 1, pc_swap bit 16) */
static void rc_pose(uint32_t veh, uint32_t car)
{
    uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
    PUSH32(g_esp, MEM32(veh + 0x64u)); PUSH32(g_esp, 0x000EBFCCu);
    g_ecx = car; sub_000E6D60();
    g_esp = esp0;
    PUSH32(g_esp, 0x000EBFD3u);
    g_ecx = car; sub_000EA070();
    g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
}

/* A real car's wheels (owner, 2026-11-12: "didn't have any tires"). The car's sim object VEH+8
 * points to its four wheel objects at +0xD8/+0xDC/+0xE0/+0xE4 (vtable 0x4186C0). A wheel is drawn
 * by its world matrix at +0x10 (rotation rows, position +0x34), which the sim writes as it steps
 * -- and a real car's sim never steps, so the matrices kept the allocator's 0xCD fill and no wheel
 * was drawn (the borrowed traffic car's wheels used to show through until 1f03c6a). The wheel's
 * mounting point in the car's frame is at +0xE4 (x y z, from the model): posed here, the car's
 * rotation and that point. (They don't spin or steer.) */
/* Spin and steer (owner, 2026-11-12: "we need to fix the wheel rotations too, it's not synced"),
 * per real-car slot, from how its car moved since the last frame: speed along its forward row
 * (forward = minus the row out of the back, +0xB8), the heading's turn toward its left; the wheels
 * roll by speed * dt / radius (the mounting height, about the wheel's radius) and the front ones
 * (mounted ahead of the middle) steer by atan(turn rate * wheelbase / speed), smoothed, 0 below
 * 1 m/s, at most 35 degrees. Positive steer = to the left. */
static struct { uint32_t car; float t, px, pz, fx, fz, spin, steer; } s_wh[MC3_CARS];

static void rc_wheels(uint32_t veh, uint32_t car, int slot, float now)
{
    static const uint32_t at[4] = { 0xD8u, 0xDCu, 0xE0u, 0xE4u };
    uint32_t sim = ghost_va_ok(veh) ? MEM32(veh + 8u) : 0u, wh[4];
    float m[12], lx[4], ly[4], lz[4], zf = 0.0f, zr = 0.0f, rad = 0.33f, base;
    float fx, fz, rx, rz, spd = 0.0f, dt;
    int k, q, nf = 0, nr = 0;
    if (!ghost_va_ok(sim)) return;
    for (q = 0; q < 12; q++) m[q] = MEMF(car + 0xA0u + 4u * (uint32_t)q);
    for (k = 0; k < 4; k++) {
        wh[k] = MEM32(sim + at[k]);
        if (!ghost_va_ok(wh[k]) || MEM32(wh[k]) != 0x004186C0u) { wh[k] = 0; continue; }
        lx[k] = MEMF(wh[k] + 0xE4u); ly[k] = MEMF(wh[k] + 0xE8u); lz[k] = MEMF(wh[k] + 0xECu);
        if (!isfinite(lx[k]) || !isfinite(ly[k]) || !isfinite(lz[k]) || fabsf(lx[k]) > 5.0f || fabsf(ly[k]) > 5.0f || fabsf(lz[k]) > 5.0f) { wh[k] = 0; continue; }
        if (lz[k] < 0.0f) { zf += lz[k]; nf++; } else { zr += lz[k]; nr++; }
        if (ly[k] > 0.2f && ly[k] < 0.6f) rad = ly[k];
    }
    base = (nf && nr) ? zr / (float)nr - zf / (float)nf : 2.6f;
    if (!(base > 1.0f && base < 5.0f)) base = 2.6f;

    /* the car's motion since the last frame */
    fx = -m[6]; fz = -m[8];                          /* forward, flat */
    { float l = sqrtf(fx * fx + fz * fz); if (l > 1e-4f) { fx /= l; fz /= l; } }
    rx = m[0]; rz = m[2];
    if (slot >= 0 && slot < MC3_CARS) {
        if (s_wh[slot].car != car) {                 /* a new car in this slot */
            s_wh[slot].car = car; s_wh[slot].t = now; s_wh[slot].px = m[9]; s_wh[slot].pz = m[11];
            s_wh[slot].fx = fx; s_wh[slot].fz = fz; s_wh[slot].spin = 0.0f; s_wh[slot].steer = 0.0f;
        }
        dt = now - s_wh[slot].t;
        if (dt > 0.0f && dt < 0.5f) {
            float dx = m[9] - s_wh[slot].px, dz = m[11] - s_wh[slot].pz, want = 0.0f, a;
            spd = (dx * fx + dz * fz) / dt;          /* + forward, - reversing */
            if (fabsf(spd) > 90.0f) spd = 0.0f;      /* a jump (teleport, new spot), not a speed */
            s_wh[slot].spin += spd * dt / rad;
            s_wh[slot].spin = fmodf(s_wh[slot].spin, 6.2831853f);
            if (fabsf(spd) > 1.0f) {                 /* the heading's turn toward the left (rad/s) */
                float turn = -((fx - s_wh[slot].fx) * rx + (fz - s_wh[slot].fz) * rz) / dt;
                want = atanf(turn * base / fabsf(spd));
                if (spd < 0.0f) want = -want;
                if (want > 0.61f) want = 0.61f; if (want < -0.61f) want = -0.61f;
            }
            a = dt * 8.0f; if (a > 1.0f) a = 1.0f;   /* smoothed */
            s_wh[slot].steer += (want - s_wh[slot].steer) * a;
        }
        if (dt != 0.0f) { s_wh[slot].t = now; s_wh[slot].px = m[9]; s_wh[slot].pz = m[11]; s_wh[slot].fx = fx; s_wh[slot].fz = fz; }
    }

    for (k = 0; k < 4; k++) {
        float r0[3], r1[3], r2[3], st = 0.0f, sp = 0.0f, cs, sn, cp, spn;
        uint32_t w = wh[k];
        if (!w) continue;
        if (slot >= 0 && slot < MC3_CARS) { sp = s_wh[slot].spin; if (lz[k] < 0.0f) st = s_wh[slot].steer; }
        /* steer: yaw about the car's up row; right' = c*right - s*back, back' = s*right + c*back */
        cs = cosf(st); sn = sinf(st);
        for (q = 0; q < 3; q++) { r0[q] = cs * m[q] - sn * m[6 + q]; r2[q] = sn * m[q] + cs * m[6 + q]; r1[q] = m[3 + q]; }
        /* spin about the wheel's own right row: rolling forward tips its up row forward */
        cp = cosf(sp); spn = sinf(sp);
        for (q = 0; q < 3; q++) {
            float u = r1[q], b = r2[q];
            MEMF(w + 0x10u + 4u * (uint32_t)q) = r0[q];
            MEMF(w + 0x1Cu + 4u * (uint32_t)q) = cp * u - spn * b;
            MEMF(w + 0x28u + 4u * (uint32_t)q) = spn * u + cp * b;
        }
        MEMF(w + 0x34u) = m[9]  + lx[k] * m[0] + ly[k] * m[3] + lz[k] * m[6];
        MEMF(w + 0x38u) = m[10] + lx[k] * m[1] + ly[k] * m[4] + lz[k] * m[7];
        MEMF(w + 0x3Cu) = m[11] + lx[k] * m[2] + ly[k] * m[5] + lz[k] * m[8];
    }
}

static int rc_name_ok(const char *s)
{
    int k;
    if (s[0] != 'v' || s[1] != 'p' || s[2] != '_') return 0;
    for (k = 3; k < 16 && s[k]; k++)
        if (!((s[k] >= 'a' && s[k] <= 'z') || (s[k] >= '0' && s[k] <= '9') || s[k] == '_')) return 0;
    return k < 16 && k > 4;
}

/* a record for this car: the local player's, copied, with the name changed (1 KB, kept) */
static uint32_t rc_record(const char *nm, int gi)
{
    uint32_t setup = MEM32(0x507B20u), slot, rec, mem, k, idx, len = (uint32_t)strlen(nm);
    uint32_t esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
    if (!ghost_va_ok(setup)) return 0;
    slot = MEM32(setup + 0x3D4u); if (slot > 7u) slot = 0;
    rec = MEM32(setup + 0x11Cu + slot * 0x2Cu);
    if (!ghost_va_ok(rec)) return 0;
    PUSH32(g_esp, 0x400u); PUSH32(g_esp, 0x0029D0CBu);
    sub_00198790();
    mem = g_eax; g_esp = esp0;
    if (!ghost_va_ok(mem)) { g_eax = eax0; g_ecx = ecx0; g_edx = edx0; return 0; }
    for (k = 0; k < 0x400u; k++) MEM8(mem + k) = MEM8(rec + k);
    if (gi >= 0 && gi < MC3_GHOSTS && s_ghosts.grec[gi][0] == 1u)   /* their own paint, parts and plate */
        for (k = 0; k < 223u; k++) MEM8(mem + 4u + k) = s_ghosts.grec[gi][1 + k];
    for (k = 0; k < 16u; k++) MEM8(mem + 0xE3u + k) = (uint8_t)(k < len ? nm[k] : 0);
    PUSH32(g_esp, mem + 0xE3u); PUSH32(g_esp, 0x0029D0A6u);
    sub_002426E0();                      /* the car table's index of this name; -1: no such car */
    idx = g_eax; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
    if (idx >= 0x400u) { fprintf(stderr, "[REALCAR] '%s': not a car the game knows\n", nm); return 0; }
    {   /* Room: a model the game hasn't loaded comes off the disc into the main heap [0x4F3918]
         * (+0xC size, +0x10 used); the Lancer's geometry alone is 1.6 MB, and the heap running
         * out stops the game for good ("Heap overrun", sub_00199490 -> sub_00188E70; frozen test,
         * 2026-11-11). So: a loaded model (sub_00241F10 on its car table entry) needs a little
         * room, an unloaded one RC_ROOM_NEW, leaving the city room to stream. */
        uint32_t heap = MEM32(0x4F3918u), loaded = 0;
        int32_t room = heap ? (int32_t)(MEM32(heap + 0xCu) - MEM32(heap + 0x10u)) : -1;
        if (ghost_va_ok(MEM32(0x51885Cu))) {
            PUSH32(g_esp, 0x0029D0BBu);
            g_ecx = MEM32(0x51885Cu) + idx * 0x1Cu; sub_00241F10();
            loaded = g_eax & 0xFFu; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
        }
        s_rc_room = room;
        if (room < (loaded ? RC_ROOM_LOADED : (s_ghosts.rc_room_kb ? (int32_t)s_ghosts.rc_room_kb * 1024 : RC_ROOM_NEW))) {
            fprintf(stderr, "[REALCAR] '%s': no room (heap free %d KB, model %s)\n", nm, room / 1024, loaded ? "loaded" : "not loaded");
            return 0;
        }
        fprintf(stderr, "[REALCAR] '%s': heap free %d KB, model %s\n", nm, room / 1024, loaded ? "loaded" : "not loaded");
    }
    return mem;
}

static uint32_t rc_look(int gi)
{
    uint32_t h = 2166136261u, k;
    if (gi < 0 || gi >= MC3_GHOSTS || s_ghosts.grec[gi][0] != 1u) return 0;
    for (k = 1; k < 224u; k++) h = (h ^ s_ghosts.grec[gi][k]) * 16777619u;
    return h | 1u;
}

static void rc_bad(const char *nm)
{
    strncpy(s_rc_bad[s_rc_badn % 16], nm, 15); s_rc_bad[s_rc_badn % 16][15] = 0; s_rc_badn++;
    s_ghosts.rc_failed++;
}

static void rc_frame(uint32_t mgr, float now)
{
    int k, r, i;
    uint32_t key0 = s_pc_player, key2 = s_ghosts.ls_runs, shown = 0;
    if (key0 != s_rc_key[0] || mgr != s_rc_key[1] || key2 != s_rc_key[2]) {   /* a new level */
        memset(s_rc, 0, sizeof s_rc);
        for (r = 0; r < RC_POOL; r++) s_rc[r].slot = -1;
        s_rc_key[0] = key0; s_rc_key[1] = mgr; s_rc_key[2] = key2;
        s_rc_next = 0.0f;
    }
    for (k = 0; k < MC3_CARS; k++) {
        struct mc3_car *c = &s_ghosts.car[k];
        char nm[16]; const char *name = 0;
        int gi = -1;
        uint32_t look = 0;
        nm[0] = 0;
        if (c->veh && s_ghosts.rc_on) {
            uint32_t n = s_ghosts.n > MC3_GHOSTS ? MC3_GHOSTS : s_ghosts.n;
            for (i = 0; i < (int)n; i++) {
                struct mc3_ghost g = s_ghosts.g[i];
                if ((g.on == 1u ? 0x80000000u + (uint32_t)i : g.on) == c->id) break;
            }
            if (i < (int)n) { memcpy(nm, s_ghosts.gname[i], 16); nm[15] = 0; if (rc_name_ok(nm)) { name = nm; gi = i; look = rc_look(i); } }
        }
        for (r = 0; r < RC_POOL; r++) if (s_rc[r].slot == k) break;
        /* A changed record no longer replaces a car (owner, 2026-11-11: every player doubled, then gone --
         * the game changes bytes of its own record while driving, each change was a new ~1.8 MB build,
         * the old and new overlapped, and the full heap left the city no traffic cars to lend) */
        if (r < RC_POOL && (!name || strcmp(s_rc[r].name, name) || !rc_valid(r))) {   /* not this slot's any more */
            if (rc_valid(r)) rc_show(s_rc[r].car, 0u); else s_rc[r].veh = s_rc[r].car = 0;
            s_rc[r].slot = -1; r = RC_POOL;
        }
        s_ghosts.rc_slot[k] = 0;
        if (!name) continue;
        if (r == RC_POOL) {                                  /* one of this model kept from before */
            for (r = 0; r < RC_POOL; r++)
                if (s_rc[r].slot < 0 && s_rc[r].veh && !strcmp(s_rc[r].name, name) &&
                    (s_rc[r].look == look || s_rc[r].owner == c->id) && rc_valid(r)) break;   /* the same look, or their own from before */
            if (r < RC_POOL) { s_rc[r].slot = k; s_rc[r].owner = c->id; rc_show(s_rc[r].car, 1u); }
        }
        if (r == RC_POOL && look && now >= s_rc_next) {     /* or a new one -- once their record has come (a
                                                              * build before it would need a second, of ~1.8 MB) */
            int b, nb = s_rc_badn < 16 ? s_rc_badn : 16;
            for (b = 0; b < nb; b++) if (!strcmp(s_rc_bad[b], name)) break;
            if (b == nb) {
                for (r = 0; r < RC_POOL; r++) if (!s_rc[r].veh) break;
                if (r == RC_POOL)                            /* full: an unused one is given up (hidden, not freed) */
                    for (r = 0; r < RC_POOL; r++) if (s_rc[r].slot < 0) break;
                if (r < RC_POOL) {
                    uint32_t rec, res = 0xE2u;
                    s_rc_next = now + 0.5f;
                    if (s_rc[r].veh && rc_valid(r)) rc_show(s_rc[r].car, 0u);
                    s_rc[r].veh = s_rc[r].car = 0; s_rc[r].slot = -1;
                    rec = rc_record(name, gi);
                    if (rec) res = rc_build_rec(rec);
                    s_ghosts.rc_last = res;
                    {   uint32_t hp = MEM32(0x4F3918u);
                        fprintf(stderr, "[REALCAR] slot %d '%s': build %X, vehicle %08X, car %08X, heap free %d -> %d KB\n", k, name, res,
                                s_rcb_veh, s_rcb_car, s_rc_room / 1024, hp ? (int)(MEM32(hp + 0xCu) - MEM32(hp + 0x10u)) / 1024 : -1); }
                    if (res == 1u) {
                        s_rc[r].veh = s_rcb_veh; s_rc[r].car = s_rcb_car; s_rc[r].cfg = s_rcb_cfg; s_rc[r].slot = k;
                        memcpy(s_rc[r].name, name, 16); s_rc[r].look = look; s_rc[r].owner = c->id;
                        s_ghosts.rc_built++;
                        if (!rc_valid(r)) {
                            fprintf(stderr, "[REALCAR] built car doesn't look right: vt %08X %08X\n", MEM32(s_rcb_car), MEM32(s_rcb_car + 8u));
                            s_rc[r].veh = s_rc[r].car = 0; s_rc[r].slot = -1; r = RC_POOL; rc_bad(name);
                        }
                    } else { r = RC_POOL; rc_bad(name); }
                }
            } else r = RC_POOL;
        }
        if (r >= RC_POOL || s_rc[r].slot != k) continue;    /* the borrowed traffic car shows meanwhile */
        {   /* the slot's matrix (right, up, forward, position), on the real car */
            uint32_t car = s_rc[r].car;
            float s = (s_ghosts.rc_flip & 1u) ? -1.0f : 1.0f;
            int q;
            for (q = 0; q < 3; q++) MEMF(car + 0xA0u + 4u * (uint32_t)q) = s * s_car_cur[k][q];
            for (q = 3; q < 6; q++) MEMF(car + 0xA0u + 4u * (uint32_t)q) = s_car_cur[k][q];
            for (q = 6; q < 9; q++) MEMF(car + 0xA0u + 4u * (uint32_t)q) = s * s_car_cur[k][q];
            MEMF(car + 0xC4u) = s_car_cur[k][9];
            MEMF(car + 0xC8u) = s_car_cur[k][10] - s_ghosts.car_yoff + s_ghosts.rc_yoff;
            MEMF(car + 0xCCu) = s_car_cur[k][11];
            rc_pose(s_rc[r].veh, car);
            rc_wheels(s_rc[r].veh, car, k, now);             /* and its wheels where they go, rolling and steering */
            car_put_far(c->veh);                             /* its traffic car out of sight */
            s_ghosts.rc_slot[k] = car;
            shown++;
        }
    }
    for (r = 0; r < RC_POOL; r++)                            /* a car whose slot went away */
        if (s_rc[r].slot >= 0 && !s_ghosts.car[s_rc[r].slot].veh) {
            if (rc_valid(r)) rc_show(s_rc[r].car, 0u);
            s_rc[r].slot = -1;
        }
    s_ghosts.rc_shown = shown;
}

/* A load starts (the loading-screen loop: garage, restart, a race): every real car is taken out of
 * its model's draw list, and the pool and the stage-1 car forgotten, before the level is torn down.
 * Left linked, the teardown walked into them and the game went on with wild pointers (garage trip
 * with 4 real cars on a 128 MB guest, 2026-11-11: "[ICALL] target ... is not code", then frozen). */
/* A built car destroyed the way the game destroys a player's (sub_00299A10, the player's base
 * destructor): the vehicle by its own scalar-deleting destructor VEH->vtbl[0](1), its config out of
 * [0x4D31CC]'s 16-slot table (sub_000F1C30; refcounted -- every build took a slot), then the vehicle
 * data (the model and paint, VEH+0x68) by its destructor vtbl[0](1). Unlinking the car alone left
 * the level holding pointers into it: the garage load crashed (2026-11-11). */
extern void sub_000F1C30(void);
static void rc_vt0_delete(uint32_t obj)
{
    uint32_t sp0 = g_esp, target;
    recomp_func_t fn;
    if (!ghost_va_ok(obj) || !ghost_va_ok(MEM32(obj))) return;
    target = MEM32(MEM32(obj));
    fn = recomp_lookup_manual(target);
    if (!fn) fn = recomp_lookup(target);
    if (!fn) { fprintf(stderr, "[REALCAR] no destructor at %08X for %08X\n", target, obj); return; }
    PUSH32(g_esp, 1u); PUSH32(g_esp, 0x00299A3Cu);
    g_ecx = obj; fn();
    g_esp = sp0;
}
static void rc_destroy(uint32_t veh, uint32_t car, uint32_t cfg)
{
    uint32_t ebx0 = g_ebx, esi0 = g_esi, edi0 = g_edi, ebp0 = g_ebp, esp0 = g_esp, eax0 = g_eax, ecx0 = g_ecx, edx0 = g_edx;
    uint32_t vd;
    if (!ghost_va_ok(veh) || MEM32(veh + 0xCu) != car) return;
    rc_show(car, 0u);                                  /* out of the draw list first */
    vd = MEM32(veh + 0x68u);
    rc_vt0_delete(veh);
    if (cfg && ghost_va_ok(MEM32(0x004D31CCu))) {
        PUSH32(g_esp, cfg); PUSH32(g_esp, 0x00299A4Bu);
        g_ecx = MEM32(0x004D31CCu); sub_000F1C30();
        g_esp = esp0;
    }
    rc_vt0_delete(vd);
    g_ebx = ebx0; g_esi = esi0; g_edi = edi0; g_ebp = ebp0; g_esp = esp0; g_eax = eax0; g_ecx = ecx0; g_edx = edx0;
}

static void rc_drop_all(void)
{
    int r, k, n = 0;
    for (r = 0; r < RC_POOL; r++) {
        if (s_rc[r].veh && rc_valid(r)) { rc_destroy(s_rc[r].veh, s_rc[r].car, s_rc[r].cfg); n++; }
        s_rc[r].veh = s_rc[r].car = s_rc[r].cfg = 0; s_rc[r].slot = -1; s_rc[r].look = s_rc[r].owner = 0;
    }
    for (k = 0; k < MC3_CARS; k++) s_ghosts.rc_slot[k] = 0;
    if (s_ghosts.pc_state == 1u && ghost_va_ok(s_ghosts.pc_car)) { rc_destroy(s_ghosts.pc_veh, s_ghosts.pc_car, s_pc_cfg); n++; }
    s_ghosts.pc_state = 0; s_ghosts.pc_car = s_ghosts.pc_veh = 0;
    s_rc_key[0] = s_rc_key[1] = s_rc_key[2] = 0;
    if (n) fprintf(stderr, "[REALCAR] a load starts: %d real car(s) destroyed\n", n);
}

/* ── The game's main heap: 47 MB on a 64 MB Xbox, more with a 128 MB window (tools_ram128.sh) ──────
 * MC3 sizes its main heap with a constant: sub_00012450 calls sub_00241AD0(x, 47, 0, 0, 0), which
 * (sub_00331E90, size << 20) takes that many MB of physical memory (sub_003320E0 -> sub_00018F06) and
 * makes it the heap [0x4F3918]. Real cars (~1.8 MB each) and a garage trip with them ran it out
 * (2026-11-11). With a 128 MB contiguous window the heap gets 61 MB more -- 108 MB, the same few MB
 * left over for textures and frame buffers as before. */
extern void sub_00241AD0_gen(void);
extern unsigned xbox_contig_window_mb(void);
void sub_00241AD0(void)
{
    if (MEM32(g_esp + 8u) == 47u && xbox_contig_window_mb() >= 128u) {
        MEM32(g_esp + 8u) = 108u;
        fprintf(stderr, "[HEAP] main heap 108 MB (contiguous window %u MB)\n", xbox_contig_window_mb());
    }
    sub_00241AD0_gen();
}

/* ── USB: a transfer cleanup that could never end (the free-roam freeze, 2026-11-11) ──────
 *
 * Caught four times with the [THREADS] dump (two of them real players): the timer thread held
 * the guest lock forever inside sub_00410234, the USB driver's routine that finishes a transfer
 * (edx = the finished TD; edi = [TD+0x14] its endpoint). After a TD that is not the last of its
 * transfer, it frees the endpoint's TDs from HeadP on (td = [0x529F80] + td->NextTD) until it has
 * done one flagged "last" (TD+0x1C & 2) -- with no TailP check and no limit. A chain without
 * such a TD (the emulated controller, usb/ohci.c, leaves one hardware never would: cause not
 * found yet) runs past TailP into physical page 0 and loops there with the lock held, so every
 * other thread -- and the picture -- stops for good.
 * Before the game's code runs, the chain is checked; if it cannot end, the finished TD is
 * flagged "last" so the loop stops after it. The rest of that one transfer's TDs leak, instead
 * of the game freezing. Each one is logged ([USB]) so the cause can be chased. */
extern void sub_00410234_gen(void);
void sub_00410234(void)
{
    static unsigned s_fixed;
    uint32_t td = g_edx, base = MEM32(0x529F80u), ed, p, tail, k, ok = 0;
    {   /* (2026-11-12, fourth look) a finished "TD" that is not a live one -- page 0, outside the
         * driver's RAM, or already freed (its endpoint field is then the free list's link, 0 at
         * the end): the walk would start on garbage and circle freed TDs (NextTD -1) for good.
         * Skip the whole routine (plain ret): that one transfer is never completed. */
        static unsigned s_skip;
        uint32_t off = td - base;
        if (off < 0x1000u || off >= 0x07FFFFE0u || (td & 0xFu) || !ghost_va_ok(MEM32(td + 0x14u))) {
            if (s_skip++ < 20)
                fprintf(stderr, "[USB] transfer cleanup on a TD that is not live (TD %08X, endpoint %08X): skipped (%u)\n",
                        td, (off < 0x07FFFFE0u) ? MEM32(td + 0x14u) : 0u, s_skip);
            g_esp += 4u;
            return;
        }
    }
    if (ghost_va_ok(td) && (MEM8(td + 0x1Cu) & 2u)) ok = 1;          /* the finished TD is the last */
    else if (ghost_va_ok(td) && ghost_va_ok(ed = MEM32(td + 0x14u))) {
        /* its short-packet path (completion code 9 and the request's +0x1D set) also stops at a
         * TD whose +0x1E is 2 ([ebp-1] cleared at loc_00410257); the error path does not */
        uint32_t rq = MEM32(td + 0x18u);
        int shortp = (MEM32(td) >> 28) == 9u && ghost_va_ok(rq) && MEM8(rq + 0x1Du) != 0;
        p = MEM32(ed + 8u) & ~0xFu; tail = MEM32(ed + 4u) & ~0xFu;
        for (k = 0; k < 64 && p && p != tail; k++) {                  /* the loop stops at a "last" TD */
            uint32_t v = base + p;
            if (!ghost_va_ok(v)) break;
            if ((MEM8(v + 0x1Cu) & 2u) || (shortp && MEM8(v + 0x1Eu) == 2u)) { ok = 1; break; }
            p = MEM32(v + 8u) & ~0xFu;
        }
    } else ok = 1;                                                     /* not ours to judge */
    if (!ok && ghost_va_ok(td)) {
        MEM8(td + 0x1Cu) |= 2u;
        if (s_fixed++ < 20)
            fprintf(stderr, "[USB] transfer cleanup could not end (TD %08X, endpoint %08X): stopped after it (%u)\n",
                    td, MEM32(td + 0x14u), s_fixed);
    }
    sub_00410234_gen();
}

/* ── USB: the transfer cleanup's walk, stopped at the endpoint's tail (inside the loop) ──────
 *
 * The check before sub_00410234 (above) never fired, yet the freeze kept coming (caught again
 * 2026-11-12 on live 6af51be8): the chain is fine when the routine starts and breaks while its
 * loop runs -- the stack showed the loop on a "TD" at guest physical 0 (a NextTD holding a
 * virtual pointer: a TD already freed and reused). The loop (loc_004102C2..4102EF) calls
 * sub_00410202 (statistics only; edx = the endpoint) once per TD with esi = the next TD it will
 * visit and bl = the current TD's "last" flag (TD+0x1C & 2); it goes on while bl is 0, and its
 * exit test also takes a next TD whose +0x1E is 2 when [ebp-1] is 0. So here, if the walk is
 * about to go on to the tail, to 0, to something that is not a physical address, or after 64
 * TDs: send it to the endpoint's tail and make the exit test true there. The driver's own exit
 * code then sets HeadP to that TD (+0x10 holds its physical address): the endpoint is empty. */
extern void sub_00410202_gen(void);
static uint32_t s_usb_last_freed;                      /* the last TD sub_0040FB2D freed (VA) */
static int usb_td_phys_ok(uint32_t base, uint32_t p)
{
    return p && !(p & 0xFu) && p < 0x08000000u && ghost_va_ok(base + p) && ghost_va_ok(base + p + 0x1Fu);
}
void sub_00410202(void)
{
    static uint32_t s_frame, s_n;
    static unsigned s_fixed;
    if (MEM32(g_esp) == 0x004102D8u && !(g_ebx & 2u)) {
        uint32_t base = MEM32(0x529F80u), ed = g_edx, next = g_esi, tail = 0, head = 0, to = 0;
        if (g_ebp != s_frame) { s_frame = g_ebp; s_n = 0; }
        if (ghost_va_ok(g_ebp) && (++s_n > 64 || !usb_td_phys_ok(base, next)
                                   || (ghost_va_ok(ed) && next == (MEM32(ed + 4u) & ~0xFu)))) {
            /* stop at the endpoint's tail; with no usable tail (a torn-down endpoint: 0), at its
             * head; failing both, on the TD just freed -- the walk only needs a readable TD whose
             * +0x1E is 2 to leave (2026-11-12: the tail was not usable and this stayed silent
             * while the walk circled freed TDs, NextTD -1, forever) */
            if (ghost_va_ok(ed)) { tail = MEM32(ed + 4u) & ~0xFu; head = MEM32(ed + 8u) & ~0xFu; }
            if (usb_td_phys_ok(base, tail)) to = tail;
            else if (usb_td_phys_ok(base, head)) to = head;
            else if (s_usb_last_freed && usb_td_phys_ok(base, s_usb_last_freed - base)) to = s_usb_last_freed - base;
            if (to) {
                g_esi = to;                            /* where the loop goes next */
                MEM8(base + to + 0x1Eu) = 2;           /* ... and stops */
                MEM8(g_ebp - 1u) = 0;
            }
            if (s_fixed++ < 20)
                fprintf(stderr, "[USB] transfer cleanup walk ran off its chain (next %08X, %u TDs,"
                        " endpoint %08X tail %08X head %08X): %s %08X (%u)\n",
                        next, s_n, ed, tail, head, to ? "stopped at" : "COULD NOT STOP, no TD", to, s_fixed);
            s_n = 0;
        }
    }
    sub_00410202_gen();
}

/* ── USB: a pending-request list that loops back on itself (the freeze, third look) ─────────
 *
 * Neither guard above fired in the freezes after them (2026-11-12, visits on live 6af52a88 and
 * next 6af52d84): the timer thread's last stack write stays at the return from the TD-cleanup
 * call (0x004102D8), so it is spinning in code that makes no calls after that -- the outer loop
 * of sub_004103D4 (loc_004103FA..4104C4), which pops request nodes off the list at
 * [this+0x42C] (next = node+0x24) until it is empty, moving some to a side list with no call at
 * all. A node in that list twice makes a cycle, and popping never empties it.
 * So the list is checked first (Floyd, bounded): a cycle is cut where it closes (that node's
 * next set to 0), the pass then ends, and the cut is logged ([USB] ...). */
extern void sub_004103D4_gen(void);
void sub_004103D4(void)
{
    static unsigned s_cut;
    uint32_t list = g_ecx;
    if (ghost_va_ok(list) && ghost_va_ok(list + 0x42Cu)) {
        uint32_t slow = MEM32(list + 0x42Cu), fast = slow, k;
        int cycle = 0;
        for (k = 0; k < 4096 && ghost_va_ok(fast) && ghost_va_ok(MEM32(fast + 0x24u)); k++) {
            slow = MEM32(slow + 0x24u);
            fast = MEM32(MEM32(fast + 0x24u) + 0x24u);
            if (!fast || !ghost_va_ok(fast)) break;
            if (slow == fast) { cycle = 1; break; }
        }
        if (cycle) {
            /* where the cycle starts: from the head and the meeting point at the same pace */
            uint32_t a = MEM32(list + 0x42Cu), b = slow, last;
            for (k = 0; a != b && k < 4096; k++) { a = MEM32(a + 0x24u); b = MEM32(b + 0x24u); }
            last = a;                                   /* go round to the node before the start */
            for (k = 0; MEM32(last + 0x24u) != a && k < 4096; k++) last = MEM32(last + 0x24u);
            if (MEM32(last + 0x24u) == a) {
                MEM32(last + 0x24u) = 0;
                if (s_cut++ < 20)
                    fprintf(stderr, "[USB] pending-request list at %08X looped (node %08X back to %08X):"
                            " cut there (%u)\n", list + 0x42Cu, last, a, s_cut);
            }
        }
    }
    sub_004103D4_gen();
}

/* ── Sound: the San Diego load's "wait until the bank's sounds have stopped", bounded ──────
 *
 * The owner's "glitchy sound" stall (2026-11-12): during the load the main thread loops in
 * sub_003D840C -- while (sub_003CFB5F(engine [0x3DAD28], owner)) { stop them (sub_003CFA41);
 * pump DirectSound (sub_003D1159) } -- the sound engine stopping every sound of a bank and
 * waiting until none is left. The voices take 16 s to minutes to be reported stopped (cause not
 * found: the deferred routines run, the audio thread keeps producing), with no frames meanwhile.
 * It always ended by itself. At that one call site (return address 0x003D8447), a busy answer
 * that has lasted MC3_SOUND_WAIT_MS (default 5000; 0 = never give up) is turned into "done". */
extern void sub_003CFB5F_gen(void);
void sub_003CFB5F(void)
{
    static double s_busy_since, s_last;
    static int s_limit = -1;
    static unsigned s_gave_up;
    uint32_t ret = MEM32(g_esp);
    struct timespec ts;
    double now;
    sub_003CFB5F_gen();
    if (ret != 0x003D8447u)
        return;
    if (s_limit < 0) {
        const char *e = getenv("MC3_SOUND_WAIT_MS");
        s_limit = e ? atoi(e) : 15000;   /* a safety net: the APU IEN fix should end these waits */
    }
    clock_gettime(CLOCK_MONOTONIC, &ts);
    now = ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
    if (!g_eax) { s_busy_since = 0; return; }
    if (!s_busy_since || now - s_last > 500) s_busy_since = now;    /* a new wait */
    s_last = now;
    if (s_limit > 0 && now - s_busy_since > s_limit) {
        if (s_gave_up++ < 20)
            fprintf(stderr, "[SOUND] gave up waiting %.1f s for a sound bank's sounds to stop (%u)\n",
                    (now - s_busy_since) / 1e3, s_gave_up);
        g_eax = 0;
        s_busy_since = 0;
    }
}
/* ── USB: freeing a TD that is not one (the freeze, fourth look, 2026-11-12) ──────────────────
 *
 * Visit 3wh2gqch (map test, live 6af5c551 era): the timer thread held the guest lock with its
 * stored esp exactly on the return slot of sub_00410234's call to sub_0040FB2D (0x004102CE) --
 * inside the routine that puts a TD back on the free list, which has no loop and no call. The
 * only way to stay there is its memory access: a "TD" pointer that is not in RAM sends the
 * writes (TD+8, +0x14, +0x1F) through the MMIO path to a device handler, which can wait for a
 * thread that needs the guest lock. So a TD outside the driver's RAM (base [0x529F80] + a physical
 * address under 128 MB, 16-byte aligned, below MMIO) is not freed (the caller
 * walks on as before), and logged. A run of more than 100000 frees in one walk is logged too, so
 * the next capture says which of the two it was. */
extern void sub_0040FB2D_gen(void);
void sub_0040FB2D(void)
{
    static unsigned s_bad, s_spin_logged;
    static uint32_t s_frame, s_n;
    uint32_t td = MEM32(g_esp + 4u);
    if (g_ebp != s_frame) { s_frame = g_ebp; s_n = 0; }
    if (++s_n == 100000u && s_spin_logged++ < 5)
        fprintf(stderr, "[USB] TD free called %u times in one walk (caller %08X, TD %08X)\n",
                s_n, MEM32(g_esp), td);
    if ((uint32_t)(td - MEM32(0x529F80u) - 0x1000u) >= 0x07FFEFE0u || td >= 0xFD000000u || (td & 0xFu)) {
        if (s_bad++ < 20)
            fprintf(stderr, "[USB] TD free of a pointer outside RAM (%08X, caller %08X): skipped (%u)\n",
                    td, MEM32(g_esp), s_bad);
        g_esp += 8u;                                   /* ret 4, as the routine would */
        return;
    }
    s_usb_last_freed = td;
    sub_0040FB2D_gen();
}

/* ── Loading: an async request that never finishes (the garage-load freeze, 2026-11-12) ────────
 *
 * Caught twice (live 6af5c551, garage load; next 6af60d74, Career load): the main thread in the
 * loading loop, sleeping 10 ms at a time in sub_001EEF60 (ret 0x001EEFA7) while entry
 * [0x4FD0C0] + (handle & ([0x4FD0DC] - 1)) * 16 has state 4 at +0xC -- an async request that never
 * completes; vblank and the guest lock were fine. Diagnostics only: after 10 s of that wait, the
 * entry, the handle and the table's other fields are logged once per wait ([LOAD]), so the next
 * capture says what the request was and which thread owes it. */
extern void sub_001EF3F0_gen(void);
void sub_001EF3F0(void)
{
    static uint32_t s_entry, s_n;
    static unsigned s_said;
    if (MEM32(g_esp) == 0x001EEFA7u) {
        uint32_t e = g_esi;
        if (e != s_entry) { s_entry = e; s_n = 0; }
        if (++s_n == 1000u && s_said++ < 10 && ghost_va_ok(e))
            fprintf(stderr, "[LOAD] waited 10 s for async request %08X (entry %08X: %08X %08X %08X %08X;"
                    " table %08X count %u, [4FD0C4] %08X)\n",
                    g_edi, e, MEM32(e), MEM32(e + 4u), MEM32(e + 8u), MEM32(e + 12u),
                    MEM32(0x4FD0C0u), MEM32(0x4FD0DCu), MEM32(0x4FD0C4u));
    } else if (MEM32(g_esp) != 0x001EEFA7u && s_n) {
        s_n = 0; s_entry = 0;
    }
    sub_001EF3F0_gen();
}

/* ── Name tags through the game's own camera (2026-11-12) ────────────────────────────────
 *
 * The approach is Leandro Dettmer's (mc3-web, src/games/remix/roam_tags.c, MIT, Copyright (c)
 * 2026 Leandro Dettmer, 2026 Laure Ladastra): read the view and the projection the game itself
 * builds for the main view, and put the point over each remote car through them. Their Remix
 * addresses, found again in the DUB Edition:
 *  - the camera applies itself with sub_002A4530 / sub_002A4560 (matrix): the camera matrix into
 *    0x51A3C0 and its inverse, the view (world -> camera, D3D row vectors), into 0x51A2B8, handed
 *    to D3D as transform 0 (Remix sub_002D3DA0, 0x559758);
 *  - then the viewport's projection: sub_002A5110 (thiscall on the viewport; fov in degrees,
 *    aspect, near, far; ret 0x10) writes the 4x4 at vp+4 (w = -view z), fov at +0x178, the D3D
 *    viewport X Y W H at +0x160 (Remix sub_002D4AE0);
 *  - the camera classes call it from sub_00120D80 (ret 0x00120DAA) and sub_00120F90 (0x00120FD7,
 *    0x00120FF6) -- the same offsets in the function as the Remix's 0x13853A / 0x13879F / 0x1387BE.
 *    Of those, the biggest viewport is the picture (the mirror and the minimap's are smaller).
 * Each car slot's point is projected right there, in the same frame as the camera, so the tag
 * cannot drift from the car; the matrices go to the page too, for players with no car yet. A
 * real car's point is its model's top (the bounds chain of roam_tags.c, checked for sense) plus
 * tag_lift; a borrowed traffic car's, its origin plus tag_head. */
extern void sub_002A5110_gen(void);
static int tag_proj(const float *vw, const float *pr, float x, float y, float z, struct mc3_tag *t)
{
    float p[4] = { x, y, z, 1.0f }, e[4], c[4];
    int i, j;
    for (j = 0; j < 4; j++) for (e[j] = 0.0f, i = 0; i < 4; i++) e[j] += p[i] * vw[4 * i + j];
    for (j = 0; j < 4; j++) for (c[j] = 0.0f, i = 0; i < 4; i++) c[j] += e[i] * pr[4 * i + j];
    if (!(c[3] > 0.5f)) return 0;                      /* behind the camera, or at it */
    t->u = 0.5f + 0.5f * c[0] / c[3];
    t->v = 0.5f - 0.5f * c[1] / c[3];
    t->w = c[3];
    return 1;
}
static float tag_model_top(uint32_t car)               /* a real car's model top over its origin, 0 = unknown */
{
    uint32_t b;
    float top;
    if (!ghost_va_ok(b = MEM32(car + 4u)) || !ghost_va_ok(b = MEM32(b + 8u)) || !ghost_va_ok(b = MEM32(b + 4u)) ||
        !ghost_va_ok(b = MEM32(b + 0x1Cu)) || !ghost_va_ok(b = MEM32(b + 4u)) || !ghost_va_ok(b = MEM32(b + 0xCu)))
        return 0.0f;
    top = MEMF(b + 0x18u);
    return top > 0.4f && top < 4.0f ? top : 0.0f;
}
static void tag_view(uint32_t vp, uint32_t ret)
{
    static uint32_t best, best_frame;
    static int said;
    uint32_t area, frame = nv2a_gl_frame_count(), k;
    float vw[16], pr[16], head, lift;
    s_ghosts.tag_calls++;
    if (ret != 0x00120DAAu && ret != 0x00120FD7u && ret != 0x00120FF6u) return;   /* not a camera applying itself */
    if (!ghost_va_ok(vp)) return;
    area = MEM32(vp + 0x168u) * MEM32(vp + 0x16Cu);
    if (area < best && frame - best_frame < 8u) return;   /* a smaller view this frame: the mirror */
    best = area; best_frame = frame;
    for (k = 0; k < 16; k++) { vw[k] = MEMF(0x0051A2B8u + 4u * k); pr[k] = MEMF(vp + 4u + 4u * k); }
    head = s_ghosts.tag_head > 0.0f ? s_ghosts.tag_head : 1.35f;
    lift = s_ghosts.tag_lift > 0.0f ? s_ghosts.tag_lift : 0.25f;
    for (k = 0; k < MC3_CARS; k++) {
        const struct mc3_car *c = &s_ghosts.car[k];
        struct mc3_tag t = { 0.0f, 0.0f, 0.0f, 0u };
        uint32_t car = s_ghosts.rc_slot[k];
        int ok;
        if (!c->veh || !c->id) { s_ghosts.tag[k].id = 0; continue; }
        if (car && ghost_va_ok(car)) {
            float top = tag_model_top(car);
            if (top > 0.0f) s_ghosts.tag_top = top;
            ok = tag_proj(vw, pr, MEMF(car + 0xC4u), MEMF(car + 0xC8u) + (top > 0.0f ? top + lift : head), MEMF(car + 0xCCu), &t);
        } else
            ok = tag_proj(vw, pr, c->x, c->y + head, c->z, &t);
        t.id = ok ? c->id : 0u;
        s_ghosts.tag[k] = t;
    }
    memcpy(s_ghosts.tag_view, vw, sizeof vw);
    memcpy(s_ghosts.tag_proj, pr, sizeof pr);
    s_ghosts.tag_vpw = MEM32(vp + 0x168u); s_ghosts.tag_vph = MEM32(vp + 0x16Cu);
    s_ghosts.tag_from = ret;
    s_ghosts.tag_frame = frame;
    s_ghosts.tag_seq++;
    if (!said) {
        said = 1;
        fprintf(stderr, "[TAGS] main view from %08X, viewport %ux%u, fov %.1f\n", (unsigned)ret,
                (unsigned)MEM32(vp + 0x168u), (unsigned)MEM32(vp + 0x16Cu), MEMF(vp + 0x178u));
    }
}
void sub_002A5110(void)
{
    uint32_t vp = g_ecx, ret = MEM32(g_esp);
    sub_002A5110_gen();                  /* builds the projection; pops its four arguments */
    tag_view(vp, ret);
}

/* <<< mc3-web-port: minimap ghosts */

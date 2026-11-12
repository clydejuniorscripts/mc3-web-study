# Notice: licences of the parts

| Part | Licence |
|---|---|
| mcdub3-nx (the tree at the root: `src/`, `config/`, `tools/`, `docs/`, `android/`, `switch/` …) | MIT, © 2026 Laure Ladastra — see `LICENSE` |
| This web port (`web/`, `port/`, and its changes throughout the tree) | MIT, © 2026 Clyde Junior and contributors — see `LICENSE` |
| xboxrecomp (`xboxrecomp/`) | MIT, © 2026 sp00nz (Ned Heller) — see `xboxrecomp/LICENSE` |
| The MCPX APU (sound chip) files from [xemu](https://github.com/xemu-project/xemu) in `xboxrecomp/src/apu/` (`apu_core.c`, `apu_dsp.c`, `apu_vp.c`, `apu_regs.h`, `apu_state.h`, `apu_debug.h`, `fpconv.h`, `apu_shim.h`) and `xboxrecomp/src/nv2a/nv2a_regs.h` | **LGPL-2.1-or-later**, © 2012 espes; 2015, 2018-2019 Jannik Vogel; 2019-2025 Matt Borgerson — full text in `xboxrecomp/LICENSES/LGPL-2.1.txt`. This port's changes to them (the stereo downmix, the bus-tag fix, the mix-bin tools) are under the same licence. |
| The Bungee font (`web/fonts/`) | SIL Open Font Licence 1.1, © David Jonathan Ross |

xboxrecomp's own third-party attribution, including algorithms it credits, is in `xboxrecomp/NOTICE`;
its contributors are listed in `xboxrecomp/CONTRIBUTORS.md`.

No part of *Midnight Club 3: DUB Edition* (© Rockstar Games / Take-Two Interactive) is included: no game
files, art, audio, video, text or code generated from the game's executable. The lifted C is produced on
your machine from your own disc and is never committed (see `.gitignore`).

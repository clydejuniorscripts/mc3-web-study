# Credits

This study would not exist without the work below. Thank you.

## The foundation

- **Laure Ladastra** — [mcdub3-nx](https://github.com/laureladastra/mcdub3-nx): *Midnight Club 3: DUB
  Edition* recompiled from the Xbox disc to C and running natively on Switch, Linux, macOS, Windows and
  Android. The web port is a fork of it. (MIT)
- **Ned Heller ([@sp00nznet](https://github.com/sp00nznet))** — [xboxrecomp](https://github.com/sp00nznet/xboxrecomp):
  the x86 lifter, XBE parsing, the Xbox kernel/XAPI runtime, the D3D8 and NV2A translation and the
  recompilation pipeline. (MIT)
- **xboxrecomp contributors** — NoRain211, DarthSidious666, dplewis, GTTeancum, andeecollard, fearkov,
  HEROTRUTH (@Heromachine), BearddOddity, Tiptup300, SpringierTrain, M0RSM4LLEO, jv36 and LukeWarm. Their
  fixes, testing and debugging insights are recorded in xboxrecomp's
  [CONTRIBUTORS.md](https://github.com/sp00nznet/xboxrecomp/blob/main/CONTRIBUTORS.md).
- **xemu** — [xemu-project/xemu](https://github.com/xemu-project/xemu): the MCPX sound-chip (APU) emulation
  used inside xboxrecomp, by **espes**, **Jannik Vogel** and **Matt Borgerson**. (LGPL-2.1-or-later) Also a
  reference for the NV2A GPU, together with **Cxbx-Reloaded** and **xboxdevwiki**.
- **Fabian Giesen** — the Morton (Z-order) texture unswizzling technique used by xboxrecomp.
- **[nfsu2-sw](https://github.com/antoxa2584x/nfsu2-sw)** by antoxa2584x — the Switch layer that inspired
  the toolkit mcdub3-nx is organised after.

## The web port

- **Clyde Junior ([@clydejuniordev](https://x.com/clydejuniordev))** — ran the study: direction, testing,
  the public test site ([dubedition.xyz](https://dubedition.xyz)) and the community
  ([Discord](https://discord.gg/shTwPRGX7f)).
- Built with **[Claude Code](https://claude.com/claude-code)** (Anthropic): several sessions in parallel did
  the porting, reverse engineering, fixes and testing described in the README.
- **Everyone who played the public test** and reported bugs — their boot reports found most of the freezes.

## Tools and libraries

[Emscripten](https://emscripten.org) and SDL2 (the WebAssembly build), [aiohttp](https://github.com/aio-libs/aiohttp)
(the game server and relay), Pillow (tools), and the **Bungee** font by David Jonathan Ross (SIL Open Font
Licence 1.1, via Google Fonts).

## The game

*Midnight Club 3: DUB Edition* is © Rockstar Games / Take-Two Interactive, developed by Rockstar San Diego.
Nothing of the game is included here; this is a non-commercial fan study and is not affiliated with or
endorsed by Rockstar Games or Take-Two Interactive.

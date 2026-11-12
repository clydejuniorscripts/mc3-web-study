#!/usr/bin/env python3
"""Browser input: pads from the page's Gamepad API, keys from its keyboard
events, both handed in from the main thread through exported functions."""
import pathlib
root = pathlib.Path.home() / "mc3-web"

def edit(rel, a, b):
    p = root / rel
    s = p.read_text()
    if b in s:
        print("already", rel); return
    assert a in s, (rel, a[:70])
    p.write_text(s.replace(a, b, 1))
    print("ok", rel)

PAD = r'''
#if defined(__EMSCRIPTEN__)
/* The browser's pads: the page polls the Gamepad API on its main thread and
 * hands each pad's state in through web_pad_set (exported); the title's
 * reads take it from here. A pad that has not reported for 2 s counts as
 * unplugged, and the keyboard is player 1 again. */
#include <emscripten.h>
static XBOX_INPUT_STATE s_web_pad[XBOX_MAX_CONTROLLERS];
static volatile double   s_web_pad_seen[XBOX_MAX_CONTROLLERS];
EMSCRIPTEN_KEEPALIVE void web_pad_set(int port, int buttons, int a, int b, int x, int y,
                                      int black, int white, int lt, int rt,
                                      int lx, int ly, int rx, int ry)
{
    XBOX_INPUT_STATE *s;
    if (port < 0 || port >= XBOX_MAX_CONTROLLERS) return;
    s = &s_web_pad[port];
    s->Gamepad.wButtons = (WORD)buttons;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_A] = (BYTE)a;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_B] = (BYTE)b;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_X] = (BYTE)x;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_Y] = (BYTE)y;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_BLACK] = (BYTE)black;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_WHITE] = (BYTE)white;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_LTRIGGER] = (BYTE)lt;
    s->Gamepad.bAnalogButtons[XBOX_BUTTON_RTRIGGER] = (BYTE)rt;
    s->Gamepad.sThumbLX = (SHORT)lx;
    s->Gamepad.sThumbLY = (SHORT)ly;
    s->Gamepad.sThumbRX = (SHORT)rx;
    s->Gamepad.sThumbRY = (SHORT)ry;
    s->dwPacketNumber++;
    s_web_pad_seen[port] = emscripten_get_now();
}
static int web_pad_read(DWORD port, XBOX_INPUT_STATE *out)
{
    if (s_web_pad_seen[port] <= 0 || emscripten_get_now() - s_web_pad_seen[port] > 2000.0)
        return 0;
    *out = s_web_pad[port];
    return 1;
}
#endif

DWORD xbox_InputGetState(DWORD dwPort, XBOX_INPUT_STATE *pState)
{
    if (dwPort >= XBOX_MAX_CONTROLLERS || !pState)
        return ERROR_DEVICE_NOT_CONNECTED;
#if defined(__EMSCRIPTEN__)
    if (web_pad_read(dwPort, pState)) {
        g_controller_connected[dwPort] = TRUE;
        return ERROR_SUCCESS;
    }
    if (dwPort != 0) {
        g_controller_connected[dwPort] = FALSE;
        return ERROR_DEVICE_NOT_CONNECTED;
    }
#endif
'''
edit("xboxrecomp/src/input/xinput_device.c",
     "\nDWORD xbox_InputGetState(DWORD dwPort, XBOX_INPUT_STATE *pState)\n{\n"
     "    if (dwPort >= XBOX_MAX_CONTROLLERS || !pState)\n"
     "        return ERROR_DEVICE_NOT_CONNECTED;\n\n#if defined(__SWITCH__)",
     PAD + "\n#if defined(__SWITCH__)")

# Keys: the page calls this directly (shared memory, a byte per key).
edit("xboxrecomp/src/input/sdl_keyboard.c",
     "void xbox_sdl_keyboard_event(int scancode, int down)\n{",
     "#if defined(__EMSCRIPTEN__)\n#include <emscripten.h>\nEMSCRIPTEN_KEEPALIVE\n#endif\n"
     "void xbox_sdl_keyboard_event(int scancode, int down)\n{")

edit("CMakeLists.txt",
     "-sEXPORTED_RUNTIME_METHODS=ENV",
     "-sEXPORTED_RUNTIME_METHODS=ENV -sEXPORTED_FUNCTIONS=_main,_web_pad_set,_xbox_sdl_keyboard_event")

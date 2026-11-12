"""cheat_test.py: the relay's speed check (relay.cheat_check) on made-up position frames, no network.
python3 relay/cheat_test.py  ->  normal driving passes, one teleport passes, sustained impossible speed is muted."""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relay

def frame(x, z):
    return b"GHST" + bytes([1]) + struct.pack("<Ifff", 0x1234, x, 0.0, z) + bytes(60)

def run(name, steps, dt=1 / 15):
    me = relay.Member(name, "lan"); t = 100.0; passed = 0; x = 0.0
    for v in steps:
        x += v * dt; t += dt
        if relay.cheat_check(me, "test", frame(x, 0.0), t): passed += 1
    return passed, len(steps), me.flags

print("driver   ", run("driver", [90.0] * 60))                       # 90 u/s, a fast car: all pass
print("teleport ", run("teleport", [60.0] * 20 + [6000.0] + [60.0] * 20))   # one 400+ jump: passes
print("cheater  ", run("cheater", [300.0] * 60))                      # 300 u/s for 4 s: muted after 1.5 s

"""admin.py -- the owner's moderation tool for the MC3 relay (relay/social.py /admin/*).

Works only on the host itself (the relay refuses /admin/ through the tunnel). Run in WSL or
Windows on the host:

    python admin.py find Bob                     players whose name / claimed name / id matches
    python admin.py ban Bob "cheating" [--days 7] [--ip]
                                                 ban by player id (a name is looked up first);
                                                 the player sees the ban number and reason.
                                                 --ip also bans their address (careful: shared
                                                 networks, e.g. a school, share one address)
    python admin.py unban Bob | unban '#12'      lift a player's bans, or ban number 12
    python admin.py bans                         the last 100 bans
    python admin.py mute Bob 30 "spam"           no chat or voice for 30 minutes (0 = until unmuted)
    python admin.py unmute Bob
    python admin.py unclaim Bob                  free a claimed name
    python admin.py reports                      players' reports about others (also in a browser on
                                                 the host: http://127.0.0.1:8090/admin/reports)

    --relay http://127.0.0.1:8090                another relay
"""
import json, sys, time, urllib.request, urllib.parse

RELAY = "http://127.0.0.1:8090"


def call(act, **a):
    data = None
    if act in ("ban", "unban", "mute", "unmute", "unclaim"):
        data = json.dumps(a).encode()
        req = urllib.request.Request(f"{RELAY}/admin/{act}", data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(f"{RELAY}/admin/{act}?" + urllib.parse.urlencode(a))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{e.code}: {e.read().decode(errors='replace')}")


def who(q):
    """a player id from an id, a claimed name or a unique name"""
    q = q.strip()
    if len(q) == 32 and all(ch in "0123456789abcdef" for ch in q.lower()):
        return q.lower()
    rows = call("find", q=q)
    exact = [r for r in rows if (r["claimed"] or "").lower() == q.lower()] or [r for r in rows if r["name"].lower() == q.lower()]
    if len(exact) == 1:
        return exact[0]["pid"]
    if not exact and len(rows) == 1:
        return rows[0]["pid"]
    show(rows)
    sys.exit(f"'{q}' matches {len(exact) or len(rows)} players: use the player id")


def when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


def show(rows):
    for r in rows:
        flags = " ".join(x for x in ("ONLINE" if r["online"] else "", "BANNED #%d" % r["ban"]["n"] if r["ban"] else "",
                                     "MUTED" if r["muted"] else "") if x)
        print(f"{r['pid']}  {r['name']:<10} claimed={r['claimed'] or '-':<10} crew={r['crew'] or '-':<10} seen {when(r['seen'])}  {flags}")


def main(argv):
    global RELAY
    if "--relay" in argv:
        i = argv.index("--relay"); RELAY = argv[i + 1]; del argv[i:i + 2]
    flag = lambda f: (f in argv) and (argv.remove(f) or True)
    def opt(f, d=None):
        if f in argv:
            i = argv.index(f); v = argv[i + 1]; del argv[i:i + 2]; return v
        return d
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "find":
        show(call("find", q=rest[0] if rest else ""))
    elif cmd == "bans":
        for b in call("bans"):
            print(f"#{b['n']:<4} {b['pid']}  {b['reason']!r:<30} until {when(b['until'])}  ip {b['ip'] or '-'}  "
                  f"{'LIFTED ' + when(b['lifted']) if b['lifted'] else 'ACTIVE'}")
    elif cmd == "ban":
        days, ip = float(opt("--days", 0)), flag("--ip")
        pid = who(rest[0]); r = call("ban", pid=pid, reason=rest[1] if len(rest) > 1 else "", days=days, ip=ip)
        print(f"ban #{r['n']} on {pid}" + (f" and address {r['ip']}" if r.get("ip") else ""))
    elif cmd == "unban":
        if rest[0].startswith("#"):
            call("unban", n=int(rest[0][1:])); print("lifted ban", rest[0])
        else:
            pid = who(rest[0]); call("unban", pid=pid); print("lifted bans on", pid)
    elif cmd == "mute":
        pid = who(rest[0]); call("mute", pid=pid, minutes=float(rest[1]) if len(rest) > 1 else 0, reason=rest[2] if len(rest) > 2 else "")
        print("muted", pid)
    elif cmd == "unmute":
        pid = who(rest[0]); call("unmute", pid=pid); print("unmuted", pid)
    elif cmd == "reports":
        for r in call("reports"):
            moves = " ".join("%.0f,%.0f" % (p[1], p[2]) for p in r["trail"][-6:])
            print(f"#{r['id']:<4} {when(r['t'])}  {r['about_name']:<10} {r['about']}  {r['why']:<9} {r['text']!r}  from {r['frm_name']}  [{moves}]")
    elif cmd == "unclaim":
        call("unclaim", name=rest[0]); print("freed the name", rest[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

// social.js -- the free-roam social layer of the MC3 web port: who the player is (a player
// id kept in this browser), crews, text chat and voice chat. The relay side is
// relay/social.py (WS /social?room=, GET /crews, GET /crew/<tag>, POST /crew).
//
// Loaded in <head>, before the page's main script: the player id (window.mc3id) is ready
// before mc3ghost picks its ghost id from it. Everything else starts at DOMContentLoaded,
// once mc3net / mc3ghost exist.
//
// Keys (none of them is one of the game's; see the GTA V layout in index.html):
//   T, or Enter while driving in free-roam: open the chat box. Enter sends, Esc closes,
//   Tab switches channel (everyone in the room / crew / nearby). While the box has focus,
//   no key reaches the game.
//   N (hold): push to talk, on the voice channel picked in the M panel.
//
// URL settings: ?FAKEMIC=1 talks with a test tone instead of the microphone (testing).
// Voice goes through the relay (no WebRTC, so no STUN / TURN to set up).
(function () {
  'use strict';
  const Q = new URLSearchParams(location.search);
  const lsGet = k => { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  // ?CREW= from the site, only when it differs from what the site sent last time (mc3.site.crew)
  const siteCrew = (() => { const v = Q.get('CREW'); if (v == null) return null; const last = lsGet('mc3.site.crew'); lsSet('mc3.site.crew', v);
                            const c = v.replace(/[^A-Za-z0-9_ ]/g, '').trim().slice(0, 10); return v !== last && c ? c : null; })();
  const hex = n => { const a = new Uint8Array(n); crypto.getRandomValues(a); return Array.from(a, b => b.toString(16).padStart(2, '0')).join(''); };

  // ── Identity: a player id and its secret, kept in this browser ─────────────────────
  // pid: 32 hex, public (others' crews and chat refer to it). key: secret; the relay keeps
  // only its hash and refuses the pid from a browser without it. gid: the id on this
  // page's position frames ('GHST'), random for each page load, so others can tell which car
  // is which; the relay learns pid <-> gid from 'hi', so the roster still maps cars to players.
  // (It was the pid's first 32 bits -- the same in every tab and window of one browser -- and a
  // page drops frames carrying its own id, so two players in one browser never saw each other,
  // whoever joined first or last: owner, 2026-11-11.) Where storage is refused, a fresh pid each visit.
  //
  // One player per open tab: identities are kept in numbered slots (slot 0: mc3.pid / mc3.key,
  // slot k: mc3.pid.k / mc3.key.k), and a tab holds its slot with a Web Lock for as long as it is
  // open. A second tab or window of the same browser finds slot 0 taken and uses slot 1 -- its own
  // player, with its own crew place and name (mc3.name.k), kept for the next time two are open.
  // (All tabs shared mc3.pid, so two players in one browser were one player to chat, crews and
  // voice: owner, 2026-11-11.) A reload asks for the slot it had first (sessionStorage).
  // Without Web Locks (old browsers): slot 0.
  const ssGet = k => { try { return sessionStorage.getItem(k) || ''; } catch (_) { return ''; } };
  const ssSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) {} };
  let pid = '', key = '', slot = 0;
  const sfx = k => k ? '.' + k : '';
  function useSlot(k) {
    slot = k; pid = lsGet('mc3.pid' + sfx(k)); key = lsGet('mc3.key' + sfx(k));
    if (!/^[0-9a-f]{32}$/.test(pid) || key.length < 16) { pid = hex(16); key = hex(16); lsSet('mc3.pid' + sfx(k), pid); lsSet('mc3.key' + sfx(k), key); }
    ssSet('mc3.slot', String(k));
  }
  const idReady = (async () => {
    const L = navigator.locks;
    if (!L || !L.request) { useSlot(0); return; }
    const hold = k => new Promise(got => {
      L.request('mc3-player-' + k, { ifAvailable: true }, lock => {
        got(!!lock);
        return lock ? new Promise(() => {}) : null;          // held until the tab closes
      }).catch(() => got(false));
    });
    // a reload: the page being left can still hold its lock for a moment, so wait for it
    // (up to 3 s) rather than become another player
    const want = ssGet('mc3.slot') === '' ? -1 : parseInt(ssGet('mc3.slot'), 10);
    if (want >= 0 && want < 16) {
      for (let t0 = Date.now(); Date.now() - t0 < 3000; await new Promise(r => setTimeout(r, 150)))
        if (await hold(want)) { useSlot(want); return; }
    }
    for (let k = 0; k < 16; k++) if (k !== want && await hold(k)) { useSlot(k); return; }
    useSlot(0);
  })().catch(() => useSlot(0));
  const gid = (() => { const a = new Uint32Array(1); do crypto.getRandomValues(a); while (a[0] < 2); return a[0] >>> 0; })();
  window.mc3id = { get pid() { return pid; }, gid, get key() { return key; }, get slot() { return slot; }, ready: idReady };

  const log = s => { try { (window.mc3log || []).push(s); } catch (_) {} };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const flagImg = cc => cc ? '<img src="/flags/' + esc(cc.toLowerCase()) + '.png" alt="' + esc(cc) + '" style="height:11px;vertical-align:-1px;margin-right:4px;border-radius:2px">' : '';
  const who = p => flagImg(p.cc) + (p.crew ? '<span style="color:#ffb300;font-weight:700">[' + esc(p.crew) + ']</span> ' : '') + '<b>' + esc(p.name || 'Player') + '</b>';

  addEventListener('DOMContentLoaded', () => { Promise.race([idReady, new Promise(r => setTimeout(r, 5000))]).then(() => { if (!pid) useSlot(0); start(); }); });

  function start() {
    const net = window.mc3net, ghost = window.mc3ghost;
    if (!net || !ghost) { log('[SOCIAL] no mc3net/mc3ghost: social layer off'); return; }
    // a second player in this browser: its own name (mc3.name.<slot>); mc3.name stays the first
    // player's, which the page itself reads and writes
    if (slot > 0) {
      const first = lsGet('mc3.name');
      let mine = lsGet('mc3.name.' + slot) || (String(ghost.me.name || 'Player').slice(0, 9) + (slot + 1));
      ghost.setName(mine); lsSet('mc3.name', first); lsSet('mc3.name.' + slot, ghost.me.name);
      setInterval(() => { const n = ghost.me.name; if (n !== mine) { mine = n; lsSet('mc3.name.' + slot, n); lsSet('mc3.name', first); } }, 500);
    }
    const HTTPS = location.protocol === 'https:';
    const RELAY = Q.get('RELAY') || (HTTPS ? ('wss://relay.' + location.hostname.replace(/^(game|play|www)\./, ''))
                                           : ('ws://' + (location.hostname || 'localhost') + ':8090'));

    // ── State ──
    let ws = null, room = null, me = null, roster = new Map(), crews = [], lastHello = '', banned = null, nameNote = '';
    const S = window.mc3social = { get me() { return me; }, roster, get room() { return room; }, pid, gid, slot,
      chat: sendChat, crew: crewOp, open: openChat, close: closeChat, voice: null, _ws: () => ws, _testPos: null };

    function connect() {
      room = net.room || 'mc3';
      try { ws = new WebSocket(RELAY + '/social?room=' + encodeURIComponent(room)); } catch (_) { ws = null; return; }
      const mine = ws;
      ws.onopen = () => { hello(true); };
      ws.onclose = () => { if (ws === mine) { ws = null; roster.clear(); renderPanel(); if (!banned) setTimeout(connect, 3000); } };
      ws.binaryType = 'arraybuffer';                  // voice frames ('VX') come as binary
      ws.onmessage = e => { if (typeof e.data !== 'string') { if (S.voice) S.voice.frame(new Uint8Array(e.data)); return; }
                            if (e.data === 'pong') return; let m; try { m = JSON.parse(e.data); } catch (_) { return; } onMsg(m); };
    }
    function say(m) { if (ws && ws.readyState === 1) { ws.send(JSON.stringify(m)); return true; } return false; }
    function hello(force) {
      const g = ghost.me, h = g.name + '|' + g.cc;
      if (!force && h === lastHello) return;
      lastHello = h; nameNote = '';
      say({ t: 'hi', pid, key, gid, name: g.name, cc: g.cc, voice: !!(S.voice && S.voice.on), hear: !S.voice || S.voice.hear });
    }
    setInterval(() => {
      if ((net.room || 'mc3') !== room && ws) { const old = ws; ws = null; try { old.close(); } catch (_) {} roster.clear(); connect(); return; }
      hello(false);
      if (ws && ws.readyState === 1) ws.send('ping');
    }, 2000);

    function onMsg(m) {
      switch (m.t) {
        case 'me': {
          const was = me && me.crew ? me.crew.tag : null;
          me = m;
          const tag = me.crew ? me.crew.tag : '';
          // the crew text on this player's position frames is the crew's tag (the relay
          // enforces it too), and the M panel's crew field only shows it now
          if (ghost.me.crew !== tag) ghost.setCrew(tag);
          if (was !== null && was !== tag) sysLine(tag ? 'You are in [' + tag + '].' : 'You are not in a crew now.');
          if (wantCrew && !me.crew) { const t = wantCrew; wantCrew = null; crewOp('join', { tag: t }); }
          wantCrew = null;
          renderPanel(); break;
        }
        case 'roster': roster.clear(); for (const p of m.players) if (p.pid !== pid) roster.set(p.pid, p); renderPanel(); break;
        case 'join': case 'upd': if (m.p.pid !== pid) roster.set(m.p.pid, m.p); renderPanel(); break;
        case 'part': roster.delete(m.pid); if (S.voice) S.voice.part(m.pid); renderPanel(); break;
        case 'chat': chatLine(m); break;
        case 'sys': if (m.text) { sysLine(m.text); panelNote(m.text, false); } break;
        case 'err': sysLine(m.text || m.e, true); panelNote(m.text || m.e, true); break;
        case 'name': nameNote = m.note || ''; if (nameNote) sysLine(nameNote, true); renderPanel(); break;
        case 'banned': showBan(m); break;
        case 'crews': crews = m.list || []; renderPanel(); break;
        case 'rtc': if (S.voice) S.voice.signal(m.from, m.d); break;
        case 'talk': if (S.voice) S.voice.talk(m.from, m.ch, m.on); break;
        case 'friends': onFriends(m); break;
        case 'pm': onPm(m); break;
        case 'where': onWhere(m); break;
        case 'lobbies': lobbyList = m.list || []; clockAt(m.now); renderPanel(); break;
        case 'lobby': onLobby(m); break;
        case 'results': onResults(m); break;
        case 'meets': meetList = m.list || []; clockAt(m.now); renderPanel(); break;
        case 'meet': onMeet(m.m); break;
        case 'rooms': roomList = m.list || []; renderPanel(); break;
      }
    }
    // ?CREW= from the site: join that crew if this player isn't in one (it must be open)
    let wantCrew = siteCrew;
    function crewOp(op, a) { return say(Object.assign({ t: 'crew', op }, a || {})); }

    // ── Chat ──────────────────────────────────────────────────────────────────────────
    const CH = { room: { label: 'ALL', color: '#e8eef7' }, crew: { label: 'CREW', color: '#ffb300' }, near: { label: 'NEAR', color: '#7dffa0' },
                 pm: { label: 'PM', color: '#ff8ad8' }, lobby: { label: 'RACE', color: '#5ec8ff' } };
    const CHS = ['room', 'crew', 'near', 'pm'];     // 'pm': to pmTo (a friend), only while there is one
    let pmTo = null;                                  // { pid, name }
    let chatCh = ['room', 'crew', 'near'].includes(lsGet('mc3.chatch')) ? lsGet('mc3.chatch') : 'room';
    const css = document.createElement('style');
    css.textContent =
      '#mc3chat{position:fixed;left:16px;bottom:37%;width:min(480px,calc(100vw - 32px));z-index:45;pointer-events:none;font:600 14px/1.35 Verdana,Geneva,sans-serif;color:#fff}' +
      '#mc3chat .lines{display:flex;flex-direction:column;gap:2px;max-height:30vh;overflow:hidden;justify-content:flex-end}' +
      '#mc3chat .ln{padding:2px 8px;border-radius:5px;text-shadow:0 1px 2px #000,0 0 6px rgba(0,0,0,.9);transition:opacity 1.2s;word-wrap:break-word}' +
      '#mc3chat.open .ln{opacity:1!important;background:rgba(0,0,0,.35)}' +
      '#mc3chat .ch{font-size:10px;letter-spacing:1px;margin-right:6px;padding:1px 5px;border-radius:3px;background:rgba(0,0,0,.5)}' +
      '#mc3chat .bar{display:none;margin-top:6px;pointer-events:auto;align-items:center;gap:6px;background:rgba(6,10,16,.88);border:1px solid rgba(255,157,28,.6);border-radius:8px;padding:5px 8px}' +
      '#mc3chat.open .bar{display:flex}' +
      '#mc3chat input{flex:1;min-width:0;background:transparent;border:0;outline:none;color:#fff;font:14px Verdana,Geneva,sans-serif}' +
      '#mc3chat .hint{font-size:10px;color:#9aa6b3;white-space:nowrap}' +
      '#mc3talk{position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:45;pointer-events:none;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;font:600 12px Verdana,Geneva,sans-serif;color:#fff}' +
      '#mc3talk span{background:rgba(6,10,16,.78);border:1px solid rgba(125,255,160,.55);border-radius:99px;padding:3px 10px;text-shadow:0 1px 2px #000}' +
      '#mc3talk span.me{border-color:#ff9d1c}' +
      '#mc3social{position:absolute;right:18px;top:18px;width:330px;max-width:calc(100vw - 36px);max-height:calc(100vh - 36px);overflow:auto;background:rgba(8,12,18,.94);border:1px solid rgba(255,157,28,.5);border-radius:12px;padding:12px 14px;color:#dfe6ee;font:12px/1.45 Verdana,Geneva,sans-serif;box-sizing:border-box;text-align:left}' +
      '#mc3social.min{width:auto;padding:6px;background:transparent;border:0}' +
      '#mc3social .mc3foot{position:sticky;bottom:-12px;margin:12px -14px -12px;padding:7px 14px;background:rgba(8,12,18,.97);border-top:1px solid rgba(255,157,28,.25);color:#8b96a3;font-size:11px;text-align:center}' +
      '#mc3social .mc3foot a{color:#ffcf7a;text-decoration:none}#mc3social .mc3foot a:hover{text-decoration:underline}' +
      '#mc3social h3{margin:0 0 8px;font:700 12px Verdana;letter-spacing:3px;color:#ffcf7a}' +
      '#mc3social h3+h3,#mc3social .sec{margin-top:14px}' +
      '#mc3social>h3[data-fold]{cursor:pointer;user-select:none}#mc3social>h3[data-fold]::before{content:"▾  ";color:#ff9d1c}' +
      '#mc3social>h3.shut::before{content:"▸  "}#mc3social>h3[data-fold]:hover{color:#fff}' +
      '#mc3social button{background:#2a2015;color:#ffcf7a;border:1px solid rgba(255,157,28,.6);border-radius:6px;padding:4px 9px;font:600 11px Verdana;cursor:pointer}' +
      '#mc3social button:hover{background:#3b2c1a}' +
      '#mc3social button:disabled{opacity:.4;cursor:default}' +
      '#mc3social button.on{background:#ff9d1c;color:#111}' +
      '#mc3social input,#mc3social select{background:rgba(10,14,20,.92);color:#fff;border:1px solid rgba(255,157,28,.45);border-radius:6px;padding:4px 7px;font:12px Verdana;outline:none}' +
      '#mc3social .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:5px 0}' +
      '#mc3social .mem{display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)}' +
      '#mc3social .mem .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#mc3social .dot{width:7px;height:7px;border-radius:50%;background:#555;flex:none}#mc3social .dot.on{background:#3ddc6a}' +
      '#mc3social .note{min-height:16px;color:#7dffa0}#mc3social .note.err{color:#ff7a6b}' +
      '#mc3social .dim{color:#8b96a3;font-size:11px}' +
      '#mc3social .meter{height:5px;background:#222;border-radius:3px;overflow:hidden;flex:1}#mc3social .meter i{display:block;height:100%;width:0;background:#3ddc6a}';
    document.head.appendChild(css);

    const box = document.createElement('div'); box.id = 'mc3chat';
    box.innerHTML = '<div class="lines"></div><div class="bar"><span class="ch"></span><input maxlength="160" autocomplete="off" spellcheck="false" placeholder="Say something"><span class="hint">Tab channel · Enter send · Esc close</span></div>';
    document.body.appendChild(box);
    const linesEl = box.querySelector('.lines'), input = box.querySelector('input'), chEl = box.querySelector('.bar .ch');
    const talkEl = document.createElement('div'); talkEl.id = 'mc3talk'; document.body.appendChild(talkEl);
    function showCh() { const c = CH[chatCh]; chEl.textContent = chatCh === 'pm' && pmTo ? 'TO ' + pmTo.name.toUpperCase() : c.label; chEl.style.color = c.color; }
    showCh();
    let chatOpen = false;
    function addLine(html, color) {
      const d = document.createElement('div'); d.className = 'ln'; d.innerHTML = html; if (color) d.style.color = color;
      d._t = performance.now(); linesEl.appendChild(d);
      while (linesEl.children.length > 40) linesEl.firstChild.remove();
    }
    function chatLine(m) {
      if (m.from && blocked.has(m.from.pid)) return;
      const c = CH[m.ch] || CH.room;
      addLine('<span class="ch" style="color:' + c.color + '">' + c.label + '</span>' + who(m.from) + ': <span style="font-weight:400">' + esc(m.text) + '</span>');
    }
    function sysLine(t, bad) { addLine('<span style="font-weight:400;font-style:italic">' + esc(t) + '</span>', bad ? '#ff9a8b' : '#9fe8ff'); }
    // closed: a line stays 10 s, then fades
    setInterval(() => { const now = performance.now();
      for (const d of linesEl.children) d.style.opacity = chatOpen || now - d._t < 10000 ? '1' : '0'; }, 500);
    function openChat(ch) {
      if (banned) return;
      if (ch && CH[ch] && (ch !== 'pm' || pmTo)) { chatCh = ch; showCh(); }
      chatOpen = true; box.classList.add('open');
      // the keys held now (W, A ...) would stay held while the player types: let them go
      try { dispatchEvent(new Event('blur')); } catch (_) {}
      input.focus();                                // now: a Tab right after T must find the box focused
    }
    function closeChat() { chatOpen = false; box.classList.remove('open'); input.value = ''; input.blur(); }
    function sendChat(text, ch) {
      text = String(text || '').trim().slice(0, 160); if (!text) return false;
      ch = ch || chatCh;
      const ok = ch === 'pm' ? (pmTo && say({ t: 'pm', to: pmTo.pid, text })) : say({ t: 'chat', ch, text });
      if (!ok) { sysLine(ch === 'pm' && !pmTo ? 'No friend to message: use Msg in the M panel.' : 'Not connected to the chat server.', true); return false; }
      return true;
    }
    const inRoam = () => { try { return window.mc3h && mc3h.mode() === 0 && !!(ghost.engine && ghost.engine.live); } catch (_) { return false; } };
    const typing = () => { const t = document.activeElement; return t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName); };
    const mapOpen = () => { const m = document.getElementById('mc3map'); return !!m && m.style.display !== 'none'; };

    // capture phase, registered before the page's own key handlers: the game never sees
    // the chat and talk keys, and nothing typed in the box reaches it either
    addEventListener('keydown', e => {
      if (document.activeElement === input) {
        if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); e.stopImmediatePropagation(); sendChat(input.value); closeChat(); }
        else if (e.code === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeChat(); }
        else if (e.code === 'Tab') { e.preventDefault(); e.stopImmediatePropagation(); const chs = CHS.slice(0, 3).concat(myLobby ? ['lobby'] : [], pmTo ? ['pm'] : []);
          chatCh = chs[(chs.indexOf(chatCh) + (e.shiftKey ? chs.length - 1 : 1)) % chs.length]; if (chatCh !== 'pm') lsSet('mc3.chatch', chatCh); showCh(); }
        else e.stopImmediatePropagation();          // typing: for the box only
        return;
      }
      if (typing() || e.ctrlKey || e.altKey || e.metaKey) return;
      const qd = /^(Digit|Numpad)([1-8])$/.exec(e.code);
      if (qd && !e.repeat && !mapOpen() && !quickKeyTaken(e.code)) { e.preventDefault(); e.stopImmediatePropagation(); quickSend(+qd[2] - 1); return; }
      if (e.code === 'KeyT' && !mapOpen()) { e.preventDefault(); e.stopImmediatePropagation(); openChat(); return; }
      if ((e.code === 'Enter' || e.code === 'NumpadEnter') && !e.repeat && !mapOpen() && inRoam()) { e.preventDefault(); e.stopImmediatePropagation(); openChat(); return; }
      if (e.code === PTT) { e.preventDefault(); e.stopImmediatePropagation(); if (!e.repeat && S.voice) S.voice.ptt(true); }
    }, true);
    addEventListener('keyup', e => { if (e.code === PTT) { e.stopImmediatePropagation(); if (S.voice) S.voice.ptt(false); } }, true);
    addEventListener('blur', () => { if (S.voice) S.voice.ptt(false); });
    input.addEventListener('blur', () => { if (chatOpen && !input.value) setTimeout(() => { if (document.activeElement !== input) closeChat(); }, 150); });

    // ── The M panel: crew and voice ───────────────────────────────────────────────────
    const PTT = 'KeyN';
    const panel = document.createElement('div'); panel.id = 'mc3social';
    // clicks in the panel are the panel's (the map underneath doesn't close)
    panel.addEventListener('pointerdown', e => e.stopPropagation());
    const host = document.getElementById('mc3map');
    if (host) host.appendChild(panel);
    // the old free-text crew field shows the crew's tag now; the crew is managed here
    const crewIn = host && host.querySelector('input[placeholder="Crew name"]');
    if (crewIn) { crewIn.readOnly = true; crewIn.title = "Your crew's tag (manage your crew in the CREW panel)"; crewIn.placeholder = 'No crew'; crewIn.style.opacity = '.75'; }
    let note = '', noteErr = false, noteT = 0, panelMin = lsGet('mc3.panelmin') === '1';
    function panelNote(t, bad) { note = t; noteErr = bad; noteT = performance.now(); renderPanel(); }
    let lastCrewsAsk = 0;
    if (host) new MutationObserver(() => { if (mapOpen()) { if (performance.now() - lastCrewsAsk > 5000) { lastCrewsAsk = performance.now(); say({ t: 'crews' }); } renderPanel(); } })
      .observe(host, { attributes: true, attributeFilter: ['style'] });

    function renderPanel() {
      if (!host || !mapOpen()) return;
      const fa = document.activeElement;                       // never under the player's typing
      if (panel.contains(fa) && /^(INPUT|SELECT)$/.test(fa.tagName) && fa.type !== 'checkbox') return;
      const V = S.voice, c = me && me.crew, lead = c && c.leader === pid;
      // folded: a small tab, so the whole map shows
      if (panelMin) { panel.classList.add('min'); panel.innerHTML = '<button data-op="punfold" title="Open the social panel">◂ SOCIAL' +
        ((friends.in || []).length + (me && me.invites ? me.invites.length : 0) ? ' •' : '') + '</button>'; return; }
      panel.classList.remove('min');
      let h = (offlineInGame() ? '<div class="note err" style="margin-bottom:8px">Offline: this drive was started from the game&#39;s own menus. ' +
               'Other players only show up when you come in through <b>Play Online</b>. Chat, friends and crews still work.</div>' : '') +
              '<button data-op="pfold" title="Fold the panel away" style="float:right;padding:1px 7px">▸</button><h3>NAME</h3>';
      const gname = ghost.me.name;
      if (me && me.claimed && me.claimed === gname) h += '<div class="row"><b>' + esc(gname) + '</b><span style="color:#7dffa0">✓ claimed: only you can use it</span><button data-op="unclaim">Let go</button></div>';
      else if (nameNote) h += '<div class="note err">' + esc(nameNote) + '</div>';
      else h += '<div class="row"><b>' + esc(gname) + '</b><button data-op="claim">Claim this name</button></div><div class="dim">Claimed, nobody else can use it' +
                (me && me.claimed ? ' (you hold <b>' + esc(me.claimed) + '</b> now; claiming moves it)' : '') + '.</div>';
      h += '<div class="row"><label class="dim"><input type="checkbox" id="sxNames"' + (hideNames ? '' : ' checked') + '> Show other players&#39; names over their cars (friends always)</label></div>';
      h += '<h3 class="sec">CREW</h3>';
      if (!ws || ws.readyState !== 1) h += '<div class="dim">Connecting to the crew server…</div>';
      else if (!c) {
        h += '<div class="row"><input id="sxTag" maxlength="10" placeholder="Crew tag (2-10)" style="width:120px">' +
             '<button data-op="create">Create</button><label class="dim"><input type="checkbox" id="sxInv"> invite only</label></div>';
        if (me && me.invites && me.invites.length) {
          h += '<div class="sec dim">INVITES</div>';
          for (const iv of me.invites) h += '<div class="mem"><span class="nm"><b style="color:#ffb300">[' + esc(iv.tag) + ']</b> from ' + esc(iv.by) + '</span>' +
            '<button data-op="join" data-tag="' + esc(iv.tag) + '">Join</button><button data-op="decline" data-tag="' + esc(iv.tag) + '">No</button></div>';
        }
        h += '<div class="sec dim">CREWS</div>';
        if (!crews.length) h += '<div class="dim">No crews yet. Make the first.</div>';
        for (const k of crews) h += '<div class="mem"><span class="nm"><b style="color:#ffb300">[' + esc(k.tag) + ']</b> ' + esc(k.name || '') +
          ' <span class="dim">' + k.members + ' member' + (k.members === 1 ? '' : 's') + ', ' + k.online + ' online</span></span>' +
          (k.open ? '<button data-op="join" data-tag="' + esc(k.tag) + '">Join</button>' : '<span class="dim">invite only</span>') + '</div>';
      } else {
        h += '<div class="row"><b style="color:#ffb300;font-size:15px">[' + esc(c.tag) + ']</b> <span>' + esc(c.name || '') + '</span>' +
             '<span class="dim">' + c.members.length + ' member' + (c.members.length === 1 ? '' : 's') + (lead ? ' · you lead' : '') + '</span></div>';
        if (lead) h += '<div class="row"><label class="dim"><input type="checkbox" id="sxOpen"' + (c.open ? ' checked' : '') + '> anyone can join (else invite only)</label></div>';
        for (const mm of c.members) h += '<div class="mem"><span class="dot' + (mm.online ? ' on' : '') + '"></span><span class="nm">' + flagImg(mm.cc) + esc(mm.name) +
          (mm.role === 'leader' ? ' <span style="color:#ffcf7a">★ leader</span>' : '') + (mm.pid === pid ? ' <span class="dim">(you)</span>' : '') + '</span>' +
          (lead && mm.pid !== pid ? '<button data-op="leader" data-pid="' + mm.pid + '" title="Make leader">★</button><button data-op="kick" data-pid="' + mm.pid + '" title="Remove from crew">✕</button>' : '') + '</div>';
        const mates = new Set(c.members.map(x => x.pid));
        const pick = [...roster.values()].filter(p => !mates.has(p.pid));
        h += '<div class="row"><select id="sxWho" style="flex:1;min-width:0">' + (pick.length ? pick.map(p => '<option value="' + p.pid + '">' + esc((p.crew ? '[' + p.crew + '] ' : '') + p.name) + '</option>').join('') : '<option value="">No one else here</option>') +
             '</select><button data-op="invite"' + (pick.length ? '' : ' disabled') + '>Invite</button></div>';
        h += '<div class="row"><button data-op="leave">Leave crew</button></div>';
      }
      if (note && performance.now() - noteT < 8000) h += '<div class="note' + (noteErr ? ' err' : '') + '">' + esc(note) + '</div>';
      // voice
      h += '<h3 class="sec">VOICE</h3>';
      h += '<div class="row"><label class="dim"><input type="checkbox" id="sxHear"' + (V && V.hear ? ' checked' : '') + '> Hear voice chat</label></div>';
      h += '<div class="row"><button data-op="voice" class="' + (V && V.on ? 'on' : '') + '">' + (V && V.on ? 'Mic on' : 'Mic off') + '</button>' +
           '<select id="sxVch">' + [['near', 'Nearby (by distance)'], ['crew', 'Crew radio']].map(([v, l]) => '<option value="' + v + '"' + (V && V.ch === v ? ' selected' : '') + '>' + l + '</option>').join('') + '</select></div>';
      h += '<div class="row dim">Hold <b style="color:#ffcf7a">N</b> to talk' + (V && V.peerCount() ? ' · heard ' + V.peerCount() + ' player' + (V.peerCount() === 1 ? '' : 's') + ' lately' : '') + '</div>';
      if (V && V.hear && V.ctx && V.ctx.state !== 'running') h += '<div class="note err">Sound is waiting for a click or key press.</div>';
      if (V && V.on) h += '<div class="row"><span class="dim">mic</span><span class="meter"><i id="sxMeter"></i></span></div>';
      if (V && V.err) h += '<div class="note err">' + esc(V.err) + '</div>';
      h += carHtml();
      h += playersHtml();
      h += roomHtml();
      h += meetHtml();
      h += racesHtml();
      h += friendsHtml();
      h += quickHtml();
      h += cloudHtml();
      h += helpHtml();
      h += '<h3 class="sec">CHAT</h3><div class="dim">T (or Enter while driving) to chat. Tab: everyone / crew / nearby.</div>';
      h += '<div class="dim" style="margin-top:6px">' + (roster.size + 1) + ' in room "' + esc(room || '') + '"</div>';
      // the footer: always there, under every section, never folded (owner, 2026-11-12)
      h += '<div class="mc3foot"><a href="https://dubedition.xyz/" target="_blank" rel="noopener">https://dubedition.xyz/</a> by @clydejuniordev</div>';
      panel.innerHTML = h;
      cloudAfterRender();
      applyFolds();
    }
    // every section folds: click its heading (owner, 2026-11-12). They start folded ("autocollapse
    // those items in M menu"): the ones a player opens are remembered in mc3.opened
    let opened = new Set((lsGet('mc3.opened') || '').split('|').filter(Boolean));
    const foldKey = h3 => (h3.firstChild && h3.firstChild.nodeType === 3 ? h3.firstChild.nodeValue : h3.textContent).trim();
    function applyFolds() {
      for (const h3 of panel.querySelectorAll(':scope > h3')) {
        const k = foldKey(h3), shut = !opened.has(k);
        h3.dataset.fold = k; h3.classList.toggle('shut', shut); h3.title = shut ? 'Show this section' : 'Hide this section';
        for (let n = h3.nextElementSibling; n && n.tagName !== 'H3' && !n.classList.contains('mc3foot'); n = n.nextElementSibling) n.style.display = shut ? 'none' : '';
      }
    }
    panel.addEventListener('click', e => { const a = e.target.closest('.mc3foot a'); if (a) setTimeout(() => a.blur(), 0); });
    panel.addEventListener('click', e => {
      const f = e.target.closest('h3[data-fold]');
      if (f && f.parentNode === panel) { const k = f.dataset.fold; if (opened.has(k)) opened.delete(k); else opened.add(k);
        lsSet('mc3.opened', [...opened].join('|')); applyFolds(); }
    });
    panel.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      const op = b.dataset.op;
      if (op === 'qedit') { quickEdit = !quickEdit; renderPanel(); return; }
      if (op === 'qreset') { QUICK = QDEF.slice(); lsSet('mc3.quick', ''); renderPanel(); return; }
      if (op === 'pfold' || op === 'punfold') { panelMin = op === 'pfold'; lsSet('mc3.panelmin', panelMin ? '1' : ''); renderPanel(); return; }
      if (cloudClick(op) || friendClick(op, b) || raceClick(op, b) || helpClick(op) || peopleClick(op, b) || carClick(op)) return;
      if (op === 'claim' || op === 'unclaim') say({ t: 'claim', on: op === 'claim' });
      else if (op === 'create') { const t = (panel.querySelector('#sxTag').value || '').trim(); crewOp('create', { tag: t, open: !panel.querySelector('#sxInv').checked }); }
      else if (op === 'join' || op === 'decline') crewOp(op, { tag: b.dataset.tag });
      else if (op === 'invite') { const p = panel.querySelector('#sxWho').value; if (p) crewOp('invite', { pid: p }); }
      else if (op === 'kick' || op === 'leader') crewOp(op, { pid: b.dataset.pid });
      else if (op === 'leave') { if (confirm('Leave your crew?')) crewOp('leave'); }
      else if (op === 'voice') { S.voice.toggle(); }
      setTimeout(() => { document.activeElement && document.activeElement.blur && panel.contains(document.activeElement) && document.activeElement.blur(); }, 0);
    });
    panel.addEventListener('change', e => {
      if (e.target.id === 'sxOpen') crewOp('open', { open: e.target.checked });
      if (e.target.id === 'sxNames') S.hideNames = !e.target.checked;
      if (e.target.id === 'sxHear') S.voice.setHear(e.target.checked);
      if (e.target.id === 'sxVch') { S.voice.ch = e.target.value; lsSet('mc3.voicech', e.target.value); }
      if (e.target.tagName === 'SELECT' || e.target.type === 'checkbox') e.target.blur();
    });
    setInterval(() => { if (mapOpen()) renderPanel(); }, 2000);

    // ── Voice: through the relay (relay/social.py 'VX' frames) ───────────────────────────
    // While N is held the microphone is encoded to Opus here (WebCodecs, 20 ms frames, ~24 kbit/s)
    // and sent on this page's social socket with the channel; the relay picks who hears it:
    // everyone in the room / the crew / players within 200 m (it knows positions and crews), and
    // drops muted players. Listening needs nothing but sound allowed (any key or click), and is on
    // by default (M panel: Hear voice chat). Each speaker is decoded and played with a volume of
    // its own: nearby by distance, crew and everyone at full volume.
    // (Was WebRTC, browser to browser, with only STUN: between homes behind ordinary routers the
    // connection often never opened, and only players who had turned voice on could hear --
    // owner, 2026-11-11: "voice chat seems to work but players cant hear each other".)
    const VOICE_RANGE = 200, FRAME = 960;                 // 20 ms at 48 kHz
    const CHI = { room: 0, crew: 1, near: 2 }, CHB = ['room', 'crew', 'near'];
    const hasCodecs = typeof AudioEncoder === 'function' && typeof AudioDecoder === 'function';
    const V = S.voice = {
      // voice channels: Nearby (by distance) and Crew radio only -- no room-wide voice (owner, 2026-11-12);
      // a saved 'room' (Everyone) lands on Nearby
      on: false, hear: lsGet('mc3.hear') !== '0', ch: lsGet('mc3.voicech') === 'crew' ? 'crew' : 'near',
      talking: false, err: hasCodecs ? '' : 'Voice needs a current Chrome, Edge, Brave or Firefox.', speaking: new Map(), ctx: null, micStream: null,
      analyser: null, enc: null, node: null, sent: 0, got: 0, spk: new Map(),      // spk: gid -> { dec, gain, next, last, ch }
      audio() {                                           // the one AudioContext (48 kHz), resumed on a gesture
        if (!this.ctx) { try { this.ctx = new AudioContext({ sampleRate: 48000 }); } catch (_) { this.ctx = new AudioContext(); } }
        if (this.ctx.state !== 'running') this.ctx.resume().catch(() => {});
        return this.ctx;
      },
      peerCount() { let n = 0; const now = performance.now(); for (const s of this.spk.values()) if (now - s.last < 60000) n++; return n; },
      toggle() { this.on ? this.stop() : this.startVoice(); },
      setHear(on) { this.hear = !!on; lsSet('mc3.hear', on ? '' : '0'); say({ t: 'hear', on: this.hear }); if (on) this.audio(); renderPanel(); },
      async startVoice() {
        this.err = '';
        if (!hasCodecs) { this.err = 'Voice needs a current Chrome, Edge, Brave or Firefox.'; renderPanel(); return; }
        const ctx = this.audio();
        try {
          if (Q.get('FAKEMIC') === '1') {                  // a test tone, for testing without a microphone
            const o = ctx.createOscillator(), g = ctx.createGain(), d = ctx.createMediaStreamDestination();
            o.frequency.value = 440; g.gain.value = 0.2; o.connect(g); g.connect(d); o.start(); this.micStream = d.stream;
          } else {
            this.micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
          }
          const src = ctx.createMediaStreamSource(this.micStream);
          this.analyser = ctx.createAnalyser(); this.analyser.fftSize = 512; src.connect(this.analyser);
          // 20 ms blocks of the microphone, from an AudioWorklet
          if (!V._wl) {
            const code = 'class Cap extends AudioWorkletProcessor{constructor(){super();this.b=new Float32Array(' + FRAME + ');this.n=0}' +
              'process(i){const c=i[0]&&i[0][0];if(c)for(let k=0;k<c.length;k++){this.b[this.n++]=c[k];if(this.n===' + FRAME + '){this.port.postMessage(this.b.slice(0));this.n=0}}return true}}' +
              'registerProcessor("mc3cap",Cap)';
            await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([code], { type: 'text/javascript' })));
            V._wl = true;
          }
          this.node = new AudioWorkletNode(ctx, 'mc3cap', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit' });
          const mute = ctx.createGain(); mute.gain.value = 0;            // keeps the worklet running, silently
          src.connect(this.node); this.node.connect(mute); mute.connect(ctx.destination);
          let ts = 0;
          this.enc = new AudioEncoder({
            output: ch => { if (!this.talking) return; const b = new Uint8Array(3 + ch.byteLength); b[0] = 86; b[1] = 88; b[2] = CHI[this.ch]; ch.copyTo(b.subarray(3));
                            if (ws && ws.readyState === 1 && ws.bufferedAmount < 64000) { ws.send(b); this.sent++; } },
            error: e => { this.err = 'Voice encoder: ' + (e && e.message || e); renderPanel(); } });
          this.enc.configure({ codec: 'opus', sampleRate: ctx.sampleRate, numberOfChannels: 1, bitrate: 24000 });
          this.node.port.onmessage = e => {
            if (!this.talking || !this.enc || this.enc.state !== 'configured') return;
            const data = new AudioData({ format: 'f32-planar', sampleRate: ctx.sampleRate, numberOfFrames: e.data.length, numberOfChannels: 1, timestamp: ts, data: e.data });
            ts += Math.round(e.data.length * 1e6 / ctx.sampleRate);
            try { this.enc.encode(data); } finally { data.close(); }
          };
        } catch (e) { this.err = 'Microphone: ' + (e && e.message || e); this.stopMic(); renderPanel(); return; }
        this.on = true; say({ t: 'voice', on: true }); log('[SOCIAL] voice on (' + V.ch + ')'); renderPanel();
      },
      stopMic() {
        try { if (this.enc && this.enc.state !== 'closed') this.enc.close(); } catch (_) {}
        try { if (this.node) this.node.disconnect(); } catch (_) {}
        if (this.micStream) for (const t of this.micStream.getTracks()) t.stop();
        this.enc = this.node = this.micStream = this.analyser = null;
      },
      stop() { this.ptt(false); this.stopMic(); this.on = false; say({ t: 'voice', on: false }); renderPanel(); },
      // a frame from the relay: 'VX', channel, the speaker's ghost id (u32), Opus
      frame(buf) {
        if (!this.hear || !hasCodecs || buf.length < 8) return;
        const ctx = this.audio(), dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
        const ch = CHB[buf[2]] || 'room', g = dv.getUint32(3, true), now = performance.now();
        if (blocked.size) { const r = [...roster.values()].find(x => (x.gid >>> 0) === g); if (r && blocked.has(r.pid)) return; }
        let s = this.spk.get(g);
        if (!s) {
          s = { gain: ctx.createGain(), next: 0, last: 0, ch, ts: 0 };
          s.gain.connect(ctx.destination);
          s.dec = new AudioDecoder({ output: d => this.play(s, d), error: () => { s.dec = null; } });
          s.dec.configure({ codec: 'opus', sampleRate: 48000, numberOfChannels: 1 });
          this.spk.set(g, s);
        }
        if (!s.dec || s.dec.state !== 'configured') { this.spk.delete(g); return; }
        s.last = now; s.ch = ch; this.got++;
        s.gain.gain.value = this.volume(g, ch);
        try { s.dec.decode(new EncodedAudioChunk({ type: 'key', timestamp: (s.ts += 20000), data: buf.subarray(7) })); } catch (_) {}
      },
      play(s, d) {
        const ctx = this.ctx, n = d.numberOfFrames, ab = ctx.createBuffer(1, n, d.sampleRate);
        try { d.copyTo(ab.getChannelData(0), { planeIndex: 0, format: 'f32-planar' }); } catch (_) { d.close(); return; }
        d.close();
        const src = ctx.createBufferSource(); src.buffer = ab; src.connect(s.gain);
        const t = ctx.currentTime;
        if (s.next < t + 0.02 || s.next > t + 0.5) s.next = t + 0.08;      // a small buffer against network jitter
        src.start(s.next); s.next += ab.duration;
      },
      // how loud a speaker is here: nearby by distance, crew and everyone at full volume
      volume(g, ch) {
        if (ch !== 'near') return 1;
        const r = [...roster.values()].find(x => (x.gid >>> 0) === g);
        const dd = dist(r);
        return dd == null ? 0.8 : Math.pow(Math.max(0.05, 1 - dd / VOICE_RANGE), 1.3);
      },
      ptt(down) {
        if (!this.on) { if (down) sysLine('Your microphone is off: turn voice on in the M panel.', true); return; }
        if (this.talking === down) return;
        this.talking = down; say({ t: 'talk', ch: this.ch, on: down });
        renderTalk();
      },
      talk(from, ch, on) { if (on) this.speaking.set(from, ch); else this.speaking.delete(from); renderTalk(); },
      part(id) { this.speaking.delete(id); },
      signal() {},                                         // WebRTC signalling: no longer used
      tick() {
        const now = performance.now();
        for (const [g, s] of this.spk) if (now - s.last > 120000) { try { s.dec && s.dec.close(); } catch (_) {} try { s.gain.disconnect(); } catch (_) {} this.spk.delete(g); }
        renderTalk();
      },
    };
    setInterval(() => V.tick(), 500);
    // sound needs a key press or a click first (browser rule): the first one starts the listening side
    const unlock = () => { if (V.hear && hasCodecs) V.audio(); };
    addEventListener('pointerdown', unlock, true); addEventListener('keydown', unlock, true);
    // mic level in the panel
    (function meter() { requestAnimationFrame(meter); const el = document.getElementById('sxMeter');
      if (!el || !V.analyser) return; const a = new Uint8Array(V.analyser.fftSize); V.analyser.getByteTimeDomainData(a);
      let m = 0; for (const x of a) m = Math.max(m, Math.abs(x - 128)); el.style.width = Math.min(100, m / 1.28 * 1.6) + '%'; })();

    // distance to another player (metres) from the positions the page already has, or null
    function myPos() { if (S._testPos) return S._testPos; const p = ghost.pos; return p ? [p[0], p[2]] : null; }
    function dist(r) {
      if (!r) return null;
      const mp = myPos(); if (!mp) return null;
      const o = (S._testOthers && S._testOthers.get(r.gid)) || ghost.others.get(r.gid);
      if (!o || !Number.isFinite(o.x)) return null;
      return Math.hypot(o.x - mp[0], o.z - mp[1]);
    }
    // a ban: the number and reason, over everything; the chat stays shut
    function showBan(m) {
      banned = m;
      const d = document.createElement('div');
      d.style.cssText = 'position:fixed;inset:0;z-index:100;background:rgba(4,6,10,.94);display:flex;align-items:center;justify-content:center;color:#eee;font:15px/1.5 Verdana,sans-serif;text-align:center';
      d.innerHTML = '<div style="max-width:520px;padding:28px;border:1px solid #c0392b;border-radius:12px;background:#140b0b">' +
        '<div style="font:800 22px Verdana;letter-spacing:3px;color:#ff6b5b;margin-bottom:12px">BANNED</div>' +
        '<div>This player is banned from playing online' + (m.until ? ' until <b>' + esc(new Date(m.until * 1000).toLocaleString()) + '</b>' : '') + '.</div>' +
        (m.reason ? '<div style="margin-top:10px">Reason: <b>' + esc(m.reason) + '</b></div>' : '') +
        '<div style="margin-top:14px;color:#aaa;font-size:13px">Ban number <b>#' + esc(m.n) + '</b>. Quote it if you ask the host about it.</div></div>';
      document.body.appendChild(d);
      closeChat(); if (S.voice && S.voice.on) S.voice.stop();
      log('[SOCIAL] banned #' + m.n + (m.reason ? ': ' + m.reason : ''));
    }
    const CHN = { near: 'NEARBY', crew: 'CREW RADIO' };
    function renderTalk() {
      let h = '';
      if (V.talking) h += '<span class="me">🎙 ' + CHN[V.ch] + '</span>';
      const now = performance.now();
      for (const [g, sp] of V.spk) {                      // heard in the last moment, and not silent here
        if (now - sp.last > 400 || sp.gain.gain.value < 0.02) continue;
        const r = [...roster.values()].find(x => (x.gid >>> 0) === g);
        h += '<span>🔊 ' + esc(r ? (r.crew ? '[' + r.crew + '] ' : '') + r.name : 'Player') + ' <small style="color:#9aa6b3">' + CHN[sp.ch] + '</small></span>';
      }
      if (talkEl._h !== h) { talkEl._h = h; talkEl.innerHTML = h; }
    }

    // ── Quick chat: preset phrases with one key (1-8) or a controller chord ──────────────
    // Keyboard: 1-8 send phrase 1-8 on the chat channel in use (ALL / CREW / NEAR / a PM),
    // unless the player bound that key to a game function. Controller, in free-roam: hold
    // Back (View) -- the phrases show -- and press the d-pad (1-4: up, right, down, left) or
    // LB / RB (5, 6). While Back is held those buttons don't reach the game (padFilter, called
    // by the page's controller code). Phrases can be changed in the M panel (mc3.quick).
    const QDEF = ['Hi!', 'GG', 'Follow me', 'Race me?', 'Wait for me', 'Nice car!', 'Thanks!', 'Sorry!'];
    let QUICK = (() => { try { const q = JSON.parse(lsGet('mc3.quick') || 'null'); if (Array.isArray(q) && q.length === 8) return q.map((x, i) => String(x || QDEF[i]).slice(0, 60)); } catch (_) {} return QDEF.slice(); })();
    let quickT = -1e9, quickEdit = false;
    function quickKeyTaken(code) { try { return typeof KEYS !== 'undefined' && Object.values(KEYS).includes(code); } catch (_) { return false; } }
    function quickSend(i) {
      const t = QUICK[i]; if (!t || banned) return;
      const now = performance.now(); if (now - quickT < 1200) return; quickT = now;   // a held key or a bounce: once
      // on the channel in use; crew without a crew, or a PM with no one to send to: everyone
      sendChat(t, (chatCh === 'crew' && !(me && me.crew)) || (chatCh === 'pm' && !pmTo) ? 'room' : chatCh);
    }
    const qEl = document.createElement('div');
    qEl.style.cssText = 'position:fixed;left:50%;bottom:16%;transform:translateX(-50%);z-index:46;pointer-events:none;display:none;' +
      'background:rgba(6,10,16,.88);border:1px solid rgba(255,157,28,.6);border-radius:10px;padding:8px 12px;font:600 13px Verdana,Geneva,sans-serif;color:#fff;' +
      'display:none;grid-template-columns:auto auto;gap:4px 18px';
    document.body.appendChild(qEl);
    const PADQ = [[12, 0, '⬆'], [15, 1, '➡'], [13, 2, '⬇'], [14, 3, '⬅'], [4, 4, 'LB'], [5, 5, 'RB']];
    let qHeld = false, qPrev = {};
    function quickPad() {
      const p = navigator.getGamepads ? [...navigator.getGamepads()].find(g => g && g.index === 0) : null;
      const back = !!(p && p.buttons[8] && p.buttons[8].pressed) && (inRoam() || !(typeof running !== 'undefined' && running));
      if (back !== qHeld) {
        qHeld = back;
        if (back) { qEl.innerHTML = PADQ.map(([, i, k]) => '<span style="color:#ffcf7a">' + k + '</span><span>' + esc(QUICK[i]) + '</span>').join(''); qEl.style.display = 'grid'; }
        else qEl.style.display = 'none';
      }
      if (!p) return;
      for (const [b, i] of PADQ) { const d = !!(p.buttons[b] && p.buttons[b].pressed); if (back && d && !qPrev[b]) quickSend(i); qPrev[b] = d; }
    }
    setInterval(quickPad, 33);
    // the page's controller code asks: what of this pad state may reach the game?
    S.padFilter = (port, st) => {
      if (port !== 0 || !qHeld || !st) return st;
      const o = st.slice(); o[0] &= ~(0x20 | 0x1 | 0x2 | 0x4 | 0x8); o[5] = 0; o[6] = 0; return o;   // BACK, d-pad; RB, LB
    };
    // Other players' names over their cars: on, or off (friends' names stay). The tags are
    // drawn by the page (index.html drawTags), which reads mc3social.hideNames.
    let hideNames = lsGet('mc3.hidenames') === '1';
    Object.defineProperty(S, 'hideNames', { get: () => hideNames, set: v => { hideNames = !!v; lsSet('mc3.hidenames', hideNames ? '1' : ''); renderPanel(); } });
    S.quick = { get list() { return QUICK; }, send: quickSend };
    function quickHtml() {
      let h = '<h3 class="sec">QUICK CHAT</h3><div class="dim">Keys 1-8, or hold Back on a controller + d-pad / LB / RB.</div>';
      if (!quickEdit) return h + '<div class="dim" style="color:#cfd6de">' + QUICK.map((q, i) => '<b style="color:#ffcf7a">' + (i + 1) + '</b> ' + esc(q)).join(' · ') +
                                 '</div><div class="row"><button data-op="qedit">Change phrases</button></div>';
      for (let i = 0; i < 8; i++) h += '<div class="row"><b style="width:14px;color:#ffcf7a">' + (i + 1) + '</b><input data-q="' + i + '" maxlength="60" value="' + esc(QUICK[i]) + '" style="flex:1;min-width:0"></div>';
      return h + '<div class="row"><button data-op="qedit">Done</button><button data-op="qreset">Back to the defaults</button></div>';
    }
    panel.addEventListener('input', e => { const i = e.target.dataset && e.target.dataset.q; if (i == null) return;
      QUICK[+i] = e.target.value.slice(0, 60) || QDEF[+i]; lsSet('mc3.quick', JSON.stringify(QUICK)); });

    // ── Race lobbies (relay/social.py) ──────────────────────────────────────────────────
    // A host makes a lobby (name, password, who may join, 2-8 players, mode / city / track /
    // laps / traffic); the RACES list shows the others' (filter: hide locked ones); members
    // ready up; the host starts: a countdown on screen (the relay's clock), then the race:
    // this page moves to the race's own relay room and asks the menu drive to put the game
    // into it (mc3menu.raceStart). Without that, it shows the settings to pick in Arcade.
    let lobbyList = [], myLobby = null, hideLocked = lsGet('mc3.hidelocked') === '1', raceMake = false, raceMsg = '', lastResults = null;
    let clockOff = 0;                                   // relay time - this browser's time (s)
    function clockAt(t) { if (t) clockOff = t - Date.now() / 1000; }
    const OPTS = () => { try { const o = window.mc3menu && mc3menu.raceOptions && mc3menu.raceOptions(); if (o && o.modes) return o; } catch (_) {}
      // what a new profile's Arcade offers first (Cruise / Capture The Flag / Paint, San Diego); the
      // race types and other cities unlock through Career, so they come after
      return { modes: ['cruise', 'ctf', 'paint', 'circuit', 'ordered', 'unordered', 'autocross', 'frenzy'], cities: ['San Diego', 'Atlanta', 'Detroit', 'Tokyo'], tracks: {} }; };
    const MODEN = { cruise: 'Cruise', ctf: 'Capture The Flag', paint: 'Paint', circuit: 'Circuit', ordered: 'Ordered checkpoints', unordered: 'Unordered checkpoints', autocross: 'Autocross', frenzy: 'Frenzy', free: 'Free' };
    const setText = st => (MODEN[st.mode] || st.mode) + ' · ' + st.city + (st.track ? ' · ' + st.track : '') + (/^(cruise|ctf|paint|free)$/.test(st.mode) ? '' : ' · ' + st.laps + ' lap' + (st.laps === 1 ? '' : 's')) + (st.traffic ? ' · traffic' : '') + (st.cls ? ' · class ' + st.cls + ' cars' : '');
    let raceStarted = null, raceMode = '';               // the race this page has driven into; how
    function onLobby(m) {
      clockAt(m.now);
      const was = myLobby;
      myLobby = m.id ? m : null;
      // mode: how the game races it, as the menu drive's raceStart says ({mode: 'link'}: one System
      // Link race, where the game draws the others itself, so the page's ghosts go off); unset otherwise
      S.race = myLobby && myLobby.state !== 'open' ? { id: myLobby.id, race: myLobby.race, room: myLobby.room, state: myLobby.state, mode: raceMode || undefined,
                                                      members: myLobby.members.map(x => ({ pid: x.pid, name: x.name })) } : null;
      if (!myLobby && was) { if (chatCh === 'lobby') { chatCh = 'room'; showCh(); } leaveRaceRoom(); }
      if (myLobby && myLobby.state === 'racing' && raceStarted !== myLobby.race) startRace(myLobby);
      if (myLobby && myLobby.state === 'open' && raceStarted) leaveRaceRoom();
      renderPanel(); renderCountdown();
    }
    // the car this player drives and its class (mc3menu.carClass, from the game's car table), for
    // the lobby's class lock: sent while in a lobby, the relay keeps only changes
    // the game's internal car name (vp_jetta_03) as a person would say it (Jetta)
    const carLabel = c => /^vp_/i.test(c) ? c.replace(/^vp_/i, '').replace(/_\d+$/, '').split('_').map(w => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ') : c;
    function carClass(car) { try { return car && window.mc3menu && mc3menu.carClass ? (mc3menu.carClass(car) || '') : ''; } catch (_) { return ''; } }
    setInterval(() => { if (myLobby && myLobby.state === 'open') { const car = ghost.me.car || ''; say({ t: 'lobby', op: 'car', car, cls: carClass(car) }); } }, 2000);
    function startRace(L) {
      raceStarted = L.race;
      if ((net.room || 'mc3') !== L.room) net.join(L.room);          // the racers' own virtual LAN
      const me = L.members.find(x => x.pid === pid);
      const arg = { role: L.host === pid ? 'host' : 'guest', race: L.race, room: L.room, settings: L.settings,
                    players: L.members.map(x => ({ name: x.name, host: x.pid === L.host })) };
      if (window.mc3menu && typeof mc3menu.raceStart === 'function') {
        Promise.resolve().then(() => mc3menu.raceStart(arg)).then(r => {
          if (r && r.mode && raceStarted === L.race) { raceMode = String(r.mode); if (S.race) S.race.mode = raceMode; }
          // the course the game got: same for everyone (the race seed) and its hash, compared in the lobby
          if (r && raceStarted === L.race && (r.sameCourse !== undefined || r.check)) say({ t: 'lobby', op: 'course', same: !!r.sameCourse, check: String(r.check || '') });
          sysLine('Race on!'); }, e => {
          raceMsg = 'The game could not be put into the race: ' + (e && e.message || e) + '. Pick it in Arcade: ' + setText(L.settings); sysLine(raceMsg, true); renderPanel(); });
      } else {
        raceMsg = (arg.role === 'host' ? 'Host the race' : 'Join ' + (L.members.find(x => x.pid === L.host) || {}).name + "'s race") + ' in the game: ' + setText(L.settings) + '.';
        sysLine(raceMsg);
      }
      log('[RACE] start ' + L.race + ' as ' + arg.role + (me ? '' : ' (not a member?)'));
    }
    function leaveRaceRoom() {
      if (!raceStarted) return;
      raceStarted = null; raceMsg = ''; raceMode = '';
      try { if (window.mc3menu && mc3menu.raceLeave) mc3menu.raceLeave(); } catch (_) {}
      if ((net.room || '').startsWith('race-')) net.join(roomFor(roomBase, cityNow()));
    }
    // a finish, from the menu drive: sent to the relay, which ranks everyone and keeps it
    try { if (window.mc3menu && typeof mc3menu.onRaceEnd === 'function') mc3menu.onRaceEnd(r => { if (r && r.ms) say({ t: 'lobby', op: 'result', ms: Math.round(r.ms), pos: r.pos | 0, car: r.car || '' }); }); } catch (_) {}
    S.raceResult = (ms, pos, car) => say({ t: 'lobby', op: 'result', ms: Math.round(ms), pos: pos | 0, car: car || '' });
    function onResults(m) {
      lastResults = m;
      const fmt = ms => Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0') + '.' + String(ms % 1000).padStart(3, '0');
      sysLine('Race results: ' + m.list.map(r => r.rank + '. ' + r.name + ' ' + fmt(r.ms)).join('  '));
      leaveRaceRoom(); renderPanel();
    }
    // the countdown, big, over the picture
    const cdEl = document.createElement('div');
    cdEl.style.cssText = 'position:fixed;inset:0;z-index:47;pointer-events:none;display:none;align-items:center;justify-content:center;flex-direction:column;' +
      'font:900 120px/1 Verdana,Geneva,sans-serif;color:#ffcf3a;text-shadow:0 4px 0 #7a1d00,0 0 30px rgba(0,0,0,.9)';
    document.body.appendChild(cdEl);
    let cdTimer = 0;
    function renderCountdown() {
      clearInterval(cdTimer);
      if (!myLobby || myLobby.state !== 'countdown' || !myLobby.start_at) { cdEl.style.display = 'none'; return; }
      const tick = () => {
        const left = myLobby && myLobby.start_at ? myLobby.start_at - (Date.now() / 1000 + clockOff) : -1;
        if (left <= -1 || !myLobby || myLobby.state === 'open') { cdEl.style.display = 'none'; clearInterval(cdTimer); return; }
        cdEl.style.display = 'flex';
        cdEl.innerHTML = (left > 0 ? Math.ceil(left) : 'GO!') + '<div style="font-size:18px;color:#fff;margin-top:14px;text-shadow:0 1px 3px #000">' + esc(myLobby.name) + ' · ' + esc(setText(myLobby.settings)) + '</div>';
      };
      tick(); cdTimer = setInterval(tick, 100);
    }
    function racesHtml() {
      let h = '<h3 class="sec">RACES</h3>';
      const L = myLobby;
      if (L) {
        const host = L.host === pid, meM = L.members.find(x => x.pid === pid) || {};
        h += '<div class="row"><b style="color:#5ec8ff">' + esc(L.name) + '</b>' + (L.locked ? ' 🔒' : '') + '<span class="dim">' + L.members.length + '/' + L.max +
             (L.who !== 'all' ? ' · ' + (L.who === 'friends' ? "host's friends" : "host's crew") : '') + ' · ' + esc(L.state) + '</span></div>';
        h += '<div class="dim" style="color:#cfd6de">' + esc(setText(L.settings)) + '</div>' +
             '<div class="dim">Ghost race (no contact): everyone online is a ghost, so nobody can ram you.</div>';
        for (const m of L.members) h += '<div class="mem"><span class="dot' + (m.online ? ' on' : '') + '"></span><span class="nm">' + flagImg(m.cc) +
          (m.crew ? '<span style="color:#ffb300">[' + esc(m.crew) + ']</span> ' : '') + esc(m.name) + (m.pid === L.host ? ' <span style="color:#ffcf7a">host</span>' : '') +
          (m.car ? ' <span class="dim">· ' + esc(carLabel(m.car)) + (m.cls ? ' (' + esc(m.cls) + ')' : '') + '</span>' : '') +
          (L.settings.cls && m.cls && m.cls !== L.settings.cls ? ' <span style="color:#ff7a6b">wrong class</span>' : '') +
          (m.pid === L.host ? '' : m.ready ? ' <span style="color:#7dffa0">✓ ready</span>' : ' <span class="dim">not ready</span>') + '</span>' +
          (host && m.pid !== pid && L.state === 'open' ? '<button data-op="rkick" data-pid="' + m.pid + '" title="Take out of the lobby">✕</button>' : '') + '</div>';
        if (L.state === 'open') {
          h += '<div class="row">' + (host ? '<button data-op="rstart"' + (L.members.length < 2 || !L.members.every(m => m.pid === pid || m.ready) ? ' disabled' : '') + '>Start race</button><button data-op="rset">Settings</button>'
                                           : '<button data-op="rready" class="' + (meM.ready ? 'on' : '') + '">' + (meM.ready ? 'Ready ✓' : 'Ready') + '</button>') +
               '<button data-op="rleave">Leave</button></div>';
        } else h += '<div class="row">' + (host ? '<button data-op="rcancel">Back to the lobby</button>' : '') + '<button data-op="rleave">Leave</button></div>';
        if (L.state !== 'open') h += courseHtml(L);
        if (raceMake && host && L.state === 'open') h += raceForm(L);
        if (raceMsg) h += '<div class="note">' + esc(raceMsg) + '</div>';
      } else if (raceMake) {
        h += raceForm(null);
      } else {
        h += '<div class="row"><button data-op="rmake">Create a race</button><label class="dim"><input type="checkbox" id="sxHideLocked"' + (hideLocked ? ' checked' : '') + '> hide locked</label></div>';
        const list = lobbyList.filter(x => !(hideLocked && x.locked));
        if (!list.length) h += '<div class="dim">No races waiting. Create one: others see it here.</div>';
        for (const x of list) h += '<div class="mem"><span class="nm"><b style="color:#5ec8ff">' + esc(x.name) + '</b>' + (x.locked ? ' 🔒' : '') +
          ' <span class="dim">' + esc(x.host) + ' · ' + x.n + '/' + x.max + ' · ' + esc(MODEN[x.settings.mode] || x.settings.mode) + ', ' + esc(x.settings.city) +
          (x.who !== 'all' ? ' · ' + (x.who === 'friends' ? 'friends' : 'crew') + ' only' : '') + '</span></span>' +
          (x.state === 'open' && x.n < x.max ? '<button data-op="rjoin" data-id="' + x.id + '" data-locked="' + (x.locked ? 1 : 0) + '">Join</button>' : '<span class="dim">' + (x.state === 'open' ? 'full' : 'racing') + '</span>') + '</div>';
      }
      if (lastResults && !(L && L.state !== 'open')) {
        const fmt = ms => Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0') + '.' + String(ms % 1000).padStart(3, '0');
        h += '<div class="dim" style="margin-top:4px">Last race: ' + lastResults.list.map(r => r.rank + '. ' + esc(r.name) + ' ' + fmt(r.ms)).join(' · ') + '</div>';
      }
      return h;
    }
    // the course: every member's game reports (raceStart: sameCourse, check); one hash for all is
    // the same course, a member with another one is flagged
    function courseHtml(L) {
      const rep = L.members.filter(m => m.course), wait = L.members.length - rep.length;
      if (!rep.length) return '';
      if (rep.some(m => !m.course.same)) return '<div class="dim">Each racer has their own course this time.</div>';
      const count = {}; for (const m of rep) count[m.course.check] = (count[m.course.check] || 0) + 1;
      const keys = Object.keys(count).sort((a, b) => count[b] - count[a]), main = keys[0];
      if (keys.length > 1 && count[keys[1]] === count[main]) return '<div class="note err">⚠ The racers&#39; courses differ: their times may not compare.</div>';
      const odd = rep.filter(m => m.course.check !== main);
      if (odd.length) return '<div class="note err">⚠ ' + odd.map(m => esc(m.name)).join(', ') + (odd.length === 1 ? ' has' : ' have') + ' a different course from the others: their times may not compare.</div>';
      return '<div class="note">✓ Same course for everyone' + (wait ? ' (' + wait + ' still loading)' : '') + '.</div>';
    }
    function raceForm(L) {
      const o = OPTS(), st = L ? L.settings : { mode: o.modes[0], city: o.cities[0], track: '', laps: 2, traffic: false };
      const sel = (id, list, v, name) => '<select id="' + id + '">' + list.map(x => '<option value="' + esc(x) + '"' + (x === v ? ' selected' : '') + '>' + esc(name ? name(x) : x) + '</option>').join('') + '</select>';
      const tracks = o.tracks && o.tracks[st.city];
      return '<div style="border:1px solid rgba(94,200,255,.35);border-radius:8px;padding:6px 8px;margin:6px 0">' +
        '<div class="row"><input id="rfName" maxlength="28" placeholder="Race name" value="' + esc(L ? L.name : ghost.me.name + "'s race") + '" style="flex:1;min-width:0"></div>' +
        '<div class="row">' + sel('rfMode', o.modes, st.mode, x => MODEN[x] || x) + sel('rfCity', o.cities, st.city) + '</div>' +
        '<div class="row">' + (tracks && tracks.length ? sel('rfTrack', tracks, st.track) : '<input id="rfTrack" maxlength="32" placeholder="Track (optional)" value="' + esc(st.track) + '" style="flex:1;min-width:0">') +
        '<span class="dim">laps</span><input id="rfLaps" type="number" min="1" max="10" value="' + st.laps + '" style="width:46px"></div>' +
        '<div class="row"><span class="dim">cars</span>' + sel('rfCls', ['', 'D', 'C', 'B', 'A'], st.cls || '', x => x ? 'class ' + x + ' only' : 'any class') + '</div>' +
        '<div class="row"><label class="dim"><input type="checkbox" id="rfTraffic"' + (st.traffic ? ' checked' : '') + '> traffic</label>' +
        sel('rfWho', ['all', 'friends', 'crew'], L ? L.who : 'all', x => x === 'all' ? 'anyone can join' : x === 'friends' ? 'my friends only' : 'my crew only') + '</div>' +
        '<div class="row"><input id="rfPw" maxlength="32" placeholder="Password (optional)" autocomplete="off" style="flex:1;min-width:0"><span class="dim">max</span>' +
        '<input id="rfMax" type="number" min="2" max="8" value="' + (L ? L.max : 8) + '" style="width:46px"' + (L ? ' disabled' : '') + '></div>' +
        '<div class="row"><button data-op="' + (L ? 'rsave' : 'rcreate') + '">' + (L ? 'Save' : 'Create') + '</button><button data-op="rmakeoff">Cancel</button></div></div>';
    }
    function formVals() {
      const v = id => { const e = panel.querySelector('#' + id); return e ? (e.type === 'checkbox' ? e.checked : e.value) : undefined; };
      return { name: v('rfName'), mode: v('rfMode'), city: v('rfCity'), track: v('rfTrack') || '', laps: +v('rfLaps') || 2, traffic: !!v('rfTraffic'),
               who: v('rfWho'), password: v('rfPw') || '', max: +v('rfMax') || 8, cls: v('rfCls') || '' };
    }
    function raceClick(op, b) {
      const lob = (o, a) => say(Object.assign({ t: 'lobby', op: o }, a || {}));
      if (op === 'rmake') { raceMake = true; renderPanel(); }
      else if (op === 'rmakeoff') { raceMake = false; renderPanel(); }
      else if (op === 'rcreate') { lob('create', formVals()); raceMake = false; }
      else if (op === 'rset') { raceMake = !raceMake; renderPanel(); }
      else if (op === 'rsave') { const v = formVals(); if (!v.password) delete v.password; delete v.max; lob('settings', v); raceMake = false; }
      else if (op === 'rjoin') { let pw = ''; if (b.dataset.locked === '1') { pw = prompt('Password for this race:') || ''; if (!pw) return true; } lob('join', { id: b.dataset.id, password: pw }); }
      else if (op === 'rready') { const me2 = myLobby && myLobby.members.find(x => x.pid === pid); lob('ready', { on: !(me2 && me2.ready) }); }
      else if (op === 'rstart') lob('start');
      else if (op === 'rleave') lob('leave');
      else if (op === 'rcancel') lob('cancel');
      else if (op === 'rkick') lob('kick', { pid: b.dataset.pid });
      else return false;
      return true;
    }
    panel.addEventListener('change', e => { if (e.target.id === 'sxHideLocked') { hideLocked = e.target.checked; lsSet('mc3.hidelocked', hideLocked ? '1' : ''); renderPanel(); } });

    // ── Players here: report, add a friend, block (this browser only) ───────────────────────
    let blocked = new Set((() => { try { return JSON.parse(lsGet('mc3.blocked') || '[]'); } catch (_) { return []; } })());
    let reportFor = null, peopleNote = '';
    const saveBlocked = () => lsSet('mc3.blocked', JSON.stringify([...blocked].slice(-500)));
    function playersHtml() {
      const L = [...roster.values()];
      let h = '<h3 class="sec">PLAYERS HERE <span class="dim" style="letter-spacing:0">' + (L.length + 1) + '</span></h3>';
      if (!L.length) return h + '<div class="dim">Nobody else in this room right now.</div>';
      const fr = new Set((friends.list || []).map(f => f.pid));
      const near = L.map(r => [r, dist(r)]).sort((a, b) => (a[1] == null ? 1e9 : a[1]) - (b[1] == null ? 1e9 : b[1]));
      for (const [r, d] of near.slice(0, 40)) {
        h += '<div class="mem"><span class="nm">' + flagImg(r.cc) + (r.crew ? '<span style="color:#ffb300">[' + esc(r.crew) + ']</span> ' : '') + esc(r.name) +
             (d != null ? ' <span class="dim">' + Math.round(d) + ' m</span>' : '') + (blocked.has(r.pid) ? ' <span class="dim">blocked</span>' : '') + '</span>' +
             (fr.has(r.pid) ? '' : '<button data-op="padd" data-pid="' + r.pid + '" title="Add as a friend">+</button>') +
             '<button data-op="pblock" data-pid="' + r.pid + '" title="' + (blocked.has(r.pid) ? 'Unblock' : 'Block: no chat or voice from them, here') + '">' + (blocked.has(r.pid) ? '↺' : '🚫') + '</button>' +
             '<button data-op="prep" data-pid="' + r.pid + '" title="Report to the host">⚑</button></div>';
        if (reportFor === r.pid) h += '<div style="border:1px solid rgba(255,122,107,.45);border-radius:8px;padding:6px 8px;margin:4px 0">' +
          '<div class="row"><span>Report ' + esc(r.name) + ':</span><select id="prWhy">' + [['cheating', 'Cheating'], ['abuse', 'Abuse / harassment'], ['spam', 'Spam'], ['griefing', 'Griefing'], ['name', 'Bad name'], ['other', 'Other']]
            .map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join('') + '</select></div>' +
          '<div class="row"><input id="prText" maxlength="200" placeholder="What happened? (optional)" style="flex:1;min-width:0"></div>' +
          '<div class="row"><button data-op="psend" data-pid="' + r.pid + '">Send report</button><button data-op="pcancel">Cancel</button></div>' +
          '<div class="dim">The host gets it with where they drove the last 20 seconds.</div></div>';
      }
      if (peopleNote) h += '<div class="note">' + esc(peopleNote) + '</div>';
      return h;
    }
    function peopleClick(op, b) {
      const id = b.dataset.pid;
      if (op === 'padd') say({ t: 'friend', op: 'add', pid: id });
      else if (op === 'pblock') { if (blocked.has(id)) blocked.delete(id); else blocked.add(id); saveBlocked(); peopleNote = blocked.has(id) ? 'Blocked: you won\'t see their chat or hear them (this browser only).' : 'Unblocked.'; renderPanel(); }
      else if (op === 'prep') { reportFor = reportFor === id ? null : id; renderPanel(); }
      else if (op === 'pcancel') { reportFor = null; renderPanel(); }
      else if (op === 'psend') { say({ t: 'report', pid: id, why: (panel.querySelector('#prWhy') || {}).value, text: (panel.querySelector('#prText') || {}).value || '' }); reportFor = null; renderPanel(); }
      else if (op === 'rmgo') { const v = (panel.querySelector('#sxRoom').value || '').trim().replace(/[^A-Za-z0-9_-]/g, '').slice(0, 24); if (v) goRoom(v); }
      else if (op === 'rmjoin') goRoom(b.dataset.room);
      else if (op === 'rmmain') goRoom(baseOf(Q.get('ROOM') || 'mc3'));
      else if (op === 'mpost') {
        const place = (panel.querySelector('#mtPlace').value || '').trim(), mins = +panel.querySelector('#mtMins').value || 0;
        if (!place) { meetNote = 'Say where.'; renderPanel(); return true; }
        const at = myPos();             // where you are (the relay's own guess by ghost id came up empty in a real game, 2026-11-11)
        say(Object.assign({ t: 'meet', place, mins }, at && isFinite(at[0]) && isFinite(at[1]) ? { x: at[0], z: at[1] } : {})); meetForm = false; renderPanel();
      }
      else if (op === 'mform') { meetForm = !meetForm; renderPanel(); }
      else if (op === 'mcancel') say({ t: 'meet', op: 'cancel', id: b.dataset.id });
      else if (op === 'mgo') { const m = meetList.find(x => x.id === b.dataset.id); if (m && m.x != null) { guide = { pid: '', gid: 0, name: m.place, x: m.x, z: m.z, t: performance.now() }; window.mc3ghost.toggleMap(false); sysLine('Meet-up "' + m.place + '" is on your screen: follow the marker.'); } }
      else return false;
      return true;
    }

    // ── Room: leave this free-roam room or go to another, without driving away ────────────
    // A room is one relay room: its own players, chat, meet-ups and lobbies list. The game keeps
    // running; only who you see changes. Race rooms (race-...) are left to the lobbies.
    let roomList = [], roomAsk = 0;
    // One room per city: players in Atlanta must not see San Diego's players (their positions are
    // another map's). The room is the chosen name (roomBase, 'mc3' by default) plus the city:
    // San Diego keeps the bare name (the test bots, the site's links), the others get -atlanta /
    // -detroit. The city is what the game really loaded (mc3menu.st.cityId, set once driving);
    // while it is unknown (menus, loading) the room stays as it is.
    const CITYN = { sd: 'San Diego', atlanta: 'Atlanta', detroit: 'Detroit' };
    const cityNow = () => { try { const c = window.mc3menu && mc3menu.st && mc3menu.st.cityId; return CITYN[c] ? c : ''; } catch (_) { return ''; } };
    const baseOf = r => String(r || 'mc3').replace(/-(atlanta|detroit)$/, '');
    const roomFor = (base, city) => base + (city && city !== 'sd' ? '-' + city : '');
    let roomBase = baseOf(net.room || Q.get('ROOM') || 'mc3'), cityShown = '';
    // the game running but not online: free-roam started from its own menus (see index.html onlineRoam)
    const offlineInGame = () => { try { return typeof running !== 'undefined' && running && !!window.mc3menu && mc3menu.online === false &&
                                                 !!(ghost.engine && ghost.engine.live); } catch (_) { return false; } };   // driving, but not online
    S.offline = offlineInGame;
    setInterval(() => {
      const here = net.room || '', c = cityNow();
      if (!c || here.startsWith('race-') || offlineInGame()) return;
      const want = roomFor(roomBase, c);
      if (here !== want) {
        if (myLobby && myLobby.state === 'open') say({ t: 'lobby', op: 'leave' });
        net.join(want); log('[SOCIAL] city ' + c + ': room ' + want);
        setTimeout(() => say({ t: 'rooms' }), 3500);
      }
      if (c !== cityShown) { if (cityShown || c !== 'sd') sysLine('You are in ' + CITYN[c] + ': you see and talk with the players driving there.'); cityShown = c; }
    }, 1000);
    function goRoom(r) {
      r = baseOf(r);
      const want = roomFor(r, cityNow());
      if (!r || want === (net.room || 'mc3')) return;
      if (myLobby) say({ t: 'lobby', op: 'leave' });
      roomBase = r; net.join(want); sysLine('Moved to room "' + r + '"' + (cityNow() ? ' (' + CITYN[cityNow()] + ')' : '') + '.'); log('[SOCIAL] room ' + want);
      setTimeout(() => say({ t: 'rooms' }), 3500);
    }
    const roomLabel = id => { const m = /^(.*)-(atlanta|detroit)$/.exec(id); return m ? m[1] + ' · ' + CITYN[m[2]] : id; };
    function roomHtml() {
      if (performance.now() - roomAsk > 8000) { roomAsk = performance.now(); say({ t: 'rooms' }); }
      const here = net.room || 'mc3', main = baseOf(Q.get('ROOM') || 'mc3'), c = cityNow();
      let h = '<h3 class="sec">ROOM</h3><div class="row">You are in <b style="color:#ffcf7a">' + esc(roomBase) + '</b>' + (c ? ' <span class="dim">· ' + CITYN[c] + '</span>' : '') +
              (roomBase !== main ? '<button data-op="rmmain">Back to ' + esc(main) + '</button>' : '') + '</div>';
      // the other rooms in this city (a room in another city can't be joined from here: it's another map)
      const sameCity = id => (/-(atlanta|detroit)$/.exec(id) || [, 'sd'])[1] === (c || 'sd');
      const others = roomList.filter(r => r.id !== here && !r.id.startsWith('race-') && sameCity(r.id)).slice(0, 8);
      for (const r of others) h += '<div class="mem"><span class="nm">' + esc(roomLabel(r.id)) + ' <span class="dim">' + r.n + ' player' + (r.n === 1 ? '' : 's') + '</span></span><button data-op="rmjoin" data-room="' + esc(r.id) + '">Go</button></div>';
      h += '<div class="row"><input id="sxRoom" maxlength="24" placeholder="Another room (name)" style="flex:1;min-width:0"><button data-op="rmgo">Go</button></div>';
      return h;
    }

    // ── Meet-ups: "meet at <place> in N minutes", for everyone in the room until it expires ──
    // Posted at where the poster is now (the relay takes their position); shown as a chat line, in
    // this list and as a marker on the M map; Go puts the guide arrow on it.
    let meetList = [], meetForm = false, meetNote = '';
    // the live meet-ups with a place, for the page's maps (the M map and the game's minimap)
    window.mc3meets = () => { const now = Date.now() / 1000 + clockOff; return meetList.filter(m => m.x != null && m.until > now && !blocked.has(m.pid)); };
    function onMeet(m) {
      if (!m || blocked.has(m.pid)) return;
      const when = Math.max(0, Math.round((m.at - (Date.now() / 1000 + clockOff)) / 60));
      addLine('<span class="ch" style="color:#ffd84a">MEET</span><b>' + esc(m.name) + '</b>: meet at <b>' + esc(m.place) + '</b> ' + (when ? 'in ' + when + ' min' : 'now') +
              (m.x != null ? ' <span style="font-size:10px;color:#9aa6b3">(on your map: M)</span>' : ''), '#ffe9a0');
    }
    function meetHtml() {
      const now = Date.now() / 1000 + clockOff, L = meetList.filter(m => m.until > now && !blocked.has(m.pid));
      let h = '<h3 class="sec">MEET-UPS</h3>';
      for (const m of L) {
        const mins = Math.round((m.at - now) / 60);
        h += '<div class="mem"><span class="nm"><b style="color:#ffd84a">' + esc(m.place) + '</b> <span class="dim">' + (mins > 0 ? 'in ' + mins + ' min' : 'now') + ' · ' + esc(m.name) + '</span></span>' +
             (m.x != null ? '<button data-op="mgo" data-id="' + m.id + '">Go</button>' : '') + (m.pid === pid ? '<button data-op="mcancel" data-id="' + m.id + '">✕</button>' : '') + '</div>';
      }
      if (meetForm) h += '<div class="row"><input id="mtPlace" maxlength="60" placeholder="Where? (e.g. the pier)" style="flex:1;min-width:0"><span class="dim">in</span>' +
        '<input id="mtMins" type="number" min="0" max="180" value="10" style="width:52px"><span class="dim">min</span></div>' +
        '<div class="row"><button data-op="mpost">Post</button><button data-op="mform">Cancel</button></div><div class="dim">The marker goes where you are now.</div>';
      else h += '<div class="row"><button data-op="mform">Post a meet-up</button>' + (L.length ? '' : '<span class="dim">none posted</span>') + '</div>';
      if (meetNote) { h += '<div class="note err">' + esc(meetNote) + '</div>'; meetNote = ''; }
      return h;
    }

    // ── Car: change it without leaving online (mc3menu.changeCar, the faster-boot session's menu
    // drive: the game's own pause > Change Vehicle > Restart Cruise, same city, still online, ~16 s).
    // Only in free-roam through Play Online. The new car reaches the others by itself (a watcher
    // calls mc3ghost.setCar), and the race lobby picks it up from there.
    let carBusy = false, carMsg = '', carErr = false;
    const canChangeCar = () => { try { return !!(window.mc3menu && typeof mc3menu.changeCar === 'function' && mc3menu.online && ghost.engine && ghost.engine.live); } catch (_) { return false; } };
    function carHtml() {
      if (!window.mc3menu || typeof mc3menu.changeCar !== 'function') return '';
      const cur = (mc3menu.st && (mc3menu.st.car || mc3menu.st.carId)) || ghost.me.car || '';
      let h = '<h3 class="sec">CAR</h3><div class="row">Driving <b style="color:#ffcf7a">' + esc(cur ? carLabel(cur) : '?') + '</b></div>';
      if (!canChangeCar()) return h + '<div class="dim">You can change car here while driving online (Play Online). In the game: Start &gt; Change Vehicle.</div>';
      const cars = (mc3menu.cars || []).filter(Boolean);
      h += '<div class="row">' + (cars.length > 1 ? '<select id="sxCar" style="flex:1;min-width:0">' + cars.map(c => '<option value="' + esc(c) + '"' + (carLabel(c) === carLabel(cur) ? ' selected' : '') + '>' + esc(carLabel(c)) + '</option>').join('') + '</select>' +
           '<button data-op="cchg"' + (carBusy ? ' disabled' : '') + '>Change</button>' : '') +
           '<button data-op="cnext"' + (carBusy ? ' disabled' : '') + '>Next car</button></div>';
      h += '<div class="dim">Takes about 15 seconds: the game restarts your cruise in the same city, still online.' +
           (cars.length < 3 ? ' Your other cars show up in the list as Next car steps through them.' : '') + '</div>';
      if (carBusy) h += '<div class="note">Changing car…</div>';
      else if (carMsg) h += '<div class="note' + (carErr ? ' err' : '') + '">' + esc(carMsg) + '</div>';
      return h;
    }
    async function changeCar(name) {
      if (carBusy || !canChangeCar()) return;
      carBusy = true; carMsg = ''; carErr = false; renderPanel();
      if (mapOpen()) window.mc3ghost.toggleMap(false);          // the game's menus show while it changes
      try {
        const r = await mc3menu.changeCar(name || undefined);
        const got = r && r.car ? carLabel(r.car) : '';
        carErr = !!(name && got && carLabel(name).toLowerCase() !== got.toLowerCase() && !got.toLowerCase().includes(String(name).toLowerCase()));
        carMsg = carErr ? 'Your profile does not have that car: still driving the ' + got + '.' : 'Now driving the ' + (got || 'new car') + '.';
        sysLine(carMsg, carErr);
      } catch (e) { carErr = true; carMsg = String(e && e.message || e); sysLine(carMsg, true); }
      finally { carBusy = false; renderPanel(); }
    }
    function carClick(op) {
      if (op === 'cchg') { const v = (panel.querySelector('#sxCar') || {}).value; changeCar(v); }
      else if (op === 'cnext') changeCar();
      else return false;
      return true;
    }

    // ── Help: send a report / download the log ───────────────────────────────────────────
    // The report is the F9 snapshot (mc3report: the last 400 log lines go to the host), with the
    // player's own words and a reference to quote; the log can also be saved as a file.
    let helpMsg = '';
    function helpHtml() {
      return '<h3 class="sec">HELP</h3><div class="dim">Something wrong? Send a report (or press F9 while it happens), or save the log to share it.</div>' +
        '<div class="row"><input id="sxRep" maxlength="70" placeholder="What happened? (optional)" style="flex:1;min-width:0"></div>' +
        '<div class="row"><button data-op="hrep">Send a report</button><button data-op="hlog">Download log</button></div>' +
        (helpMsg ? '<div class="note">' + esc(helpMsg) + '</div>' : '');
    }
    function helpClick(op) {
      if (op === 'hrep') {
        const words = (panel.querySelector('#sxRep') || {}).value || '';
        let n = 0; try { n = window.mc3report ? window.mc3report(('panel: ' + words).slice(0, 80)) : 0; } catch (_) {}
        let ref = ''; try { ref = typeof bootRep !== 'undefined' && bootRep.id ? bootRep.id : ''; } catch (_) {}
        helpMsg = n ? 'Sent ' + n + ' log lines to the host' + (ref ? '. Your reference: ' + ref : '') + '. Thanks!' : 'Could not send the report.';
        renderPanel(); return true;
      }
      if (op === 'hlog') {
        let ref = ''; try { ref = typeof bootRep !== 'undefined' && bootRep.id ? bootRep.id : ''; } catch (_) {}
        const all = window.mc3log || [];
        const head = ['MC3 Web log', 'saved ' + new Date().toISOString(), 'page ' + location.href.replace(/[?#].*$/, ''), 'browser ' + navigator.userAgent,
                      'reference ' + (ref || '-'), 'player ' + pid.slice(0, 8), 'lines ' + all.length, ''];
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([head.concat(all.map(String)).join('\n')], { type: 'text/plain' }));
        a.download = 'mc3-log-' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.txt';
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 30000);
        helpMsg = 'Saved ' + all.length + ' lines as ' + a.download + '.';
        renderPanel(); return true;
      }
      return false;
    }

    // ── Friends: list, requests, private messages, join, colours ─────────────────────────
    // relay/social.py keeps the list (up to 250), requests and messages for offline friends.
    // Each friend has a colour of their own (from their player id): their arrow and name on the
    // M map here, and -- through mc3social.ghostStyle(gid), read by the page's map, minimap and
    // name tags -- wherever they are drawn.
    let friends = { list: [], in: [], out: [] }, fAdd = '', guide = null, lastPm = null;
    const FCOL = ['#4fc3ff', '#ff5ec4', '#7dff6a', '#b48cff', '#ff8a3d', '#3dffe0', '#ffef5a', '#ff5a5a'];
    const fcol = id => { let h = 0; for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return FCOL[h % FCOL.length]; };
    const friendByGid = new Map();
    function onFriends(m) {
      friends = m; friendByGid.clear();
      for (const f of m.list) { f.color = fcol(f.pid); if (f.online && f.gid && f.room === room) friendByGid.set(f.gid >>> 0, f); }
      renderPanel();
    }
    function onPm(m) {
      if (m.from && m.from.pid !== pid && blocked.has(m.from.pid)) return;
      const mine = m.from.pid === pid, other = mine ? friends.list.find(f => f.pid === m.to) : m.from;
      if (!mine) { lastPm = { pid: m.from.pid, name: m.from.name }; if (!pmTo) pmTo = lastPm; }
      addLine('<span class="ch" style="color:' + CH.pm.color + '">' + (mine ? 'TO ' + esc(other ? other.name : '?') : 'PM') + '</span>' +
              (mine ? '' : who(m.from) + ': ') + '<span style="font-weight:400">' + esc(m.text) + '</span>' +
              (m.old ? ' <span style="font-size:10px;color:#9aa6b3">(' + esc(new Date(m.ts).toLocaleString()) + ')</span>' : ''), CH.pm.color);
    }
    // style for a ghost: friends in their colour, crew mates in crew orange; null for others
    S.ghostStyle = g => {
      const f = friendByGid.get(g >>> 0); if (f) return { friend: true, crew: false, color: f.color, name: f.name };
      const tag = me && me.crew ? me.crew.tag : '';
      if (tag) for (const r of roster.values()) if ((r.gid >>> 0) === (g >>> 0) && r.crew === tag) return { friend: false, crew: true, color: '#ffb300', name: r.name };
      return null;
    };
    S.friends = () => friends;
    function msgTo(f) { pmTo = { pid: f.pid, name: f.name }; if (mapOpen()) window.mc3ghost.toggleMap(false); openChat('pm'); }
    // Join: into the friend's room, then a guide to where they are (and a jump there if the page
    // can move the car: mc3ghost.teleport, when the engine side has one)
    function joinFriend(f) { say({ t: 'where', pid: f.pid }); }
    function onWhere(m) {
      const f = friends.list.find(x => x.pid === m.pid); const nm = f ? f.name : 'Your friend';
      if (m.error) { panelNote(nm + (m.error === 'offline' ? ' is offline.' : ': ' + m.error), true); return; }
      if (m.room !== (net.room || 'mc3')) { net.join(m.room); sysLine('Joining ' + nm + "'s room \"" + m.room + '\"…'); }
      if (!m.roam) { panelNote(nm + ' is online but not driving in free-roam right now.', false); return; }
      guide = { pid: m.pid, gid: m.gid >>> 0, name: nm, x: m.x, z: m.z, t: performance.now() };
      if (mapOpen()) window.mc3ghost.toggleMap(false);
      if (typeof window.mc3ghost.teleportTo === 'function') teleportToFriend(guide.gid, nm);
      else sysLine(nm + ' is on your map: follow the marker at the top of the screen.');
    }
    // Join's jump (engine 6af4b3df+, mc3ghost.teleportTo): once the friend's position frames arrive in
    // this room (after the room switch) and this player is driving, the car is put 8 m behind them;
    // the engine answers in its next frame (teleport().state: '1' done, 'e..' failed). If anything
    // fails, the guide arrow stays.
    let tpBusy = false;
    async function teleportToFriend(g, nm) {
      if (tpBusy) return; tpBusy = true;
      const wait = ms => new Promise(r => setTimeout(r, ms));
      let why = '';
      try {
        sysLine('Taking you to ' + nm + '…');
        let o = null;
        for (let t0 = performance.now(); performance.now() - t0 < 12000; await wait(250)) {
          o = ghost.others.get(g >>> 0);
          if (o && performance.now() - o.t < 1500 && inRoam()) break;
          o = null;
        }
        if (!o) { why = inRoam() ? nm + "'s position didn't arrive" : 'you are not driving in free-roam'; return; }
        const r = ghost.teleportTo(g >>> 0);
        if (typeof r === 'string' || !r) { why = r || 'the game said no'; return; }
        let st = null;
        for (let t0 = performance.now(); performance.now() - t0 < 4000; await wait(100)) {
          st = ghost.teleport();
          if (st && !st.pending && st.state !== '0') break;
        }
        if (st && st.state === '1') { sysLine('You are with ' + nm + ' now.'); log('[SOCIAL] teleported to ' + nm); guide = null; return; }
        why = 'the game could not move the car' + (st ? ' (' + st.state + ')' : '');
      } catch (e) { why = String(e && e.message || e); }
      finally {
        tpBusy = false;
        if (why) { sysLine('Could not take you there: ' + why + '. Follow the marker at the top of the screen.', true); log('[SOCIAL] teleport failed: ' + why); }
        renderPanel();
      }
    }
    // the guide: direction and distance to the friend, at the top of the picture
    const guideEl = document.createElement('div');
    guideEl.style.cssText = 'position:fixed;top:44px;left:50%;transform:translateX(-50%);z-index:45;pointer-events:none;font:700 14px Verdana,Geneva,sans-serif;color:#fff;text-shadow:0 1px 3px #000;display:none';
    document.body.appendChild(guideEl);
    let gPrev = null, gHead = null;
    setInterval(() => {
      if (!guide) { guideEl.style.display = 'none'; return; }
      const o = ghost.others.get(guide.gid); if (o) { guide.x = o.x; guide.z = o.z; }
      const mp = myPos();
      if (!mp || performance.now() - guide.t > 600000) { guideEl.style.display = 'none'; if (mp) guide = null; return; }
      if (gPrev && Math.hypot(mp[0] - gPrev[0], mp[1] - gPrev[1]) > 1.5) gHead = Math.atan2(mp[1] - gPrev[1], mp[0] - gPrev[0]);
      gPrev = mp;
      const dx = guide.x - mp[0], dz = guide.z - mp[1], d = Math.hypot(dx, dz);
      if (d < 25) { sysLine('You found ' + guide.name + '.'); guide = null; guideEl.style.display = 'none'; return; }
      let arrow = '';
      if (gHead != null) { let a = Math.atan2(dz, dx) - gHead; a = Math.atan2(Math.sin(a), Math.cos(a));
        arrow = a > 2.75 || a < -2.75 ? '⬇' : a > 1.96 ? '↙' : a > 1.18 ? '⬅' : a > 0.39 ? '↖' : a > -0.39 ? '⬆' : a > -1.18 ? '↗' : a > -1.96 ? '➡' : '↘';
        // the map's z grows up the screen: a turn toward +z from +x is to the left
      }
      const f = friends.list.find(x => x.pid === guide.pid);
      guideEl.innerHTML = '<span style="font-size:22px;vertical-align:-3px">' + arrow + '</span> <span style="color:' + (f ? f.color : '#fff') + '">' + esc(guide.name) + '</span> ' + Math.round(d) + ' m';
      guideEl.style.display = '';
    }, 300);
    // friends on the M map: an arrow in their colour, with their name, at any distance
    const fov = document.createElement('canvas'); fov.style.cssText = 'position:fixed!important;pointer-events:none;z-index:51!important;display:none!important';
    document.body.appendChild(fov);
    (function drawFriends() {
      requestAnimationFrame(drawFriends);
      const mapCv = host && host.querySelector('canvas');
      const nowS = Date.now() / 1000 + clockOff, mts = meetList.filter(m => m.x != null && m.until > nowS && !blocked.has(m.pid));
      if (!mapCv || !mapOpen() || (!friendByGid.size && !mts.length)) { fov.style.setProperty('display', 'none', 'important'); return; }
      const r = mapCv.getBoundingClientRect(); if (!r.width) return;
      if (fov.width !== Math.round(r.width) || fov.height !== Math.round(r.height)) { fov.width = Math.round(r.width); fov.height = Math.round(r.height); }
      // !important: the page's own rules stretch every canvas
      for (const [k, v] of [['display', 'block'], ['left', r.left + 'px'], ['top', r.top + 'px'], ['width', r.width + 'px'], ['height', r.height + 'px']]) fov.style.setProperty(k, v, 'important');
      const x = fov.getContext('2d'); x.clearRect(0, 0, fov.width, fov.height);
      const now = performance.now();
      // meet-ups: the M map draws them itself now (index.html drawPlaces, from window.mc3meets), in the
      // same marker the game's minimap shows them with (owner, 2026-11-12: minimap and M map match)
      for (const [g, f] of friendByGid) {
        const o = ghost.others.get(g); if (!o || now - o.t > 5000) continue;
        const [u, v] = ghost.uv(o.sx ?? o.x, o.sz ?? o.z), px = u * fov.width, py = v * fov.height;
        const h = o.h || 0, dir = Math.atan2(-Math.sin(h) * (ghost.cal.flipZ ? -1 : 1), -Math.cos(h) * (ghost.cal.flipX ? -1 : 1));
        x.save(); x.translate(px, py); x.rotate(dir + Math.PI / 2);
        x.fillStyle = f.color; x.strokeStyle = '#000'; x.lineWidth = 2.5;
        x.beginPath(); x.moveTo(0, -12); x.lineTo(-8, 9); x.lineTo(8, 9); x.closePath(); x.fill(); x.stroke(); x.restore();
        x.font = '700 13px Verdana'; x.textAlign = 'center'; x.lineWidth = 3; x.strokeStyle = 'rgba(0,0,0,.85)'; x.fillStyle = f.color;
        x.strokeText(f.name, px, py - 16); x.fillText(f.name, px, py - 16);
      }
    })();
    function friendsHtml() {
      const L = friends.list || [], on = L.filter(f => f.online).length;
      let h = '<h3 class="sec">FRIENDS <span class="dim" style="letter-spacing:0">' + on + ' online · ' + L.length + '</span></h3>';
      h += '<div class="row"><input id="sxFriend" maxlength="10" placeholder="Add by name" style="flex:1;min-width:0" value="' + esc(fAdd) + '"><button data-op="fadd">Add</button></div>';
      const here = [...roster.values()].filter(p => !L.some(f => f.pid === p.pid));
      if (here.length) h += '<div class="row"><select id="sxFhere" style="flex:1;min-width:0">' + here.map(p => '<option value="' + p.pid + '">' + esc((p.crew ? '[' + p.crew + '] ' : '') + p.name) + '</option>').join('') +
                           '</select><button data-op="faddhere">Add friend</button></div>';
      for (const r of friends.in || []) h += '<div class="mem"><span class="nm">' + flagImg(r.cc) + '<b>' + esc(r.name) + '</b> wants to be friends</span>' +
        '<button data-op="facc" data-pid="' + r.pid + '">Accept</button><button data-op="fdec" data-pid="' + r.pid + '">No</button></div>';
      for (const r of friends.out || []) h += '<div class="mem"><span class="nm dim">Asked ' + esc(r.name) + '…</span><button data-op="fcan" data-pid="' + r.pid + '">Cancel</button></div>';
      for (const f of L.slice().sort((a, b) => b.online - a.online)) {
        h += '<div class="mem"><span class="dot' + (f.online ? ' on' : '') + '"></span><span class="nm"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;background:' + f.color + '"></span>' +
          flagImg(f.cc) + (f.crew ? '<span style="color:#ffb300">[' + esc(f.crew) + ']</span> ' : '') + esc(f.name) +
          (f.online ? (f.room !== room ? ' <span class="dim">· room ' + esc(f.room) + '</span>' : '') : ' <span class="dim">· seen ' + (f.seen ? esc(new Date(f.seen * 1000).toLocaleDateString()) : '?') + '</span>') + '</span>' +
          '<button data-op="fmsg" data-pid="' + f.pid + '" title="Private message">Msg</button>' +
          (f.online ? '<button data-op="fjoin" data-pid="' + f.pid + '" title="Go to them in free-roam">Join</button>' : '') +
          '<button data-op="frem" data-pid="' + f.pid + '" title="Remove friend">✕</button></div>';
      }
      if (!L.length && !(friends.in || []).length) h += '<div class="dim">No friends yet. A name works if its player claimed it or is online now.</div>';
      if (guide) h += '<div class="row dim">Guiding you to ' + esc(guide.name) + ' <button data-op="fstop">Stop</button></div>';
      return h;
    }
    function friendClick(op, b) {
      const f = (friends.list || []).find(x => x.pid === b.dataset.pid);
      if (op === 'fadd') { const v = panel.querySelector('#sxFriend').value.trim(); if (v) { say({ t: 'friend', op: 'add', name: v }); fAdd = ''; } }
      else if (op === 'faddhere') { const v = panel.querySelector('#sxFhere').value; if (v) say({ t: 'friend', op: 'add', pid: v }); }
      else if (op === 'facc') say({ t: 'friend', op: 'accept', pid: b.dataset.pid });
      else if (op === 'fdec' || op === 'fcan') say({ t: 'friend', op: 'decline', pid: b.dataset.pid });
      else if (op === 'frem') { if (f && confirm('Remove ' + f.name + ' from your friends?')) say({ t: 'friend', op: 'remove', pid: f.pid }); }
      else if (op === 'fmsg') { if (f) msgTo(f); }
      else if (op === 'fjoin') { if (f) joinFriend(f); }
      else if (op === 'fstop') { guide = null; renderPanel(); }
      else return false;
      return true;
    }

    // ── QR code (byte mode, error correction M, versions 1-10), written for this page ──
    // qrMatrix(bytes) -> array of rows of booleans (true = dark). Enough for a link with a code.
    const qrMatrix = (() => {
      // per version: [ec codewords per block, [blocks, data codewords]...] at level M
      const SPEC = [null, [10, [1, 16]], [16, [1, 28]], [26, [1, 44]], [18, [2, 32]], [24, [2, 43]], [16, [4, 27]],
        [18, [4, 31]], [22, [2, 38], [2, 39]], [22, [3, 36], [2, 37]], [26, [4, 43], [1, 44]]];
      const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
      const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
      for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 256) x ^= 0x11D; }
      for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
      const mul = (a, b) => a && b ? EXP[LOG[a] + LOG[b]] : 0;
      function rs(data, n) {                                   // n error-correction codewords
        let g = [1];
        for (let i = 0; i < n; i++) { const ng = new Array(g.length + 1).fill(0);
          for (let j = 0; j < g.length; j++) { ng[j] ^= g[j]; ng[j + 1] ^= mul(g[j], EXP[i]); } g = ng; }
        const r = new Array(n).fill(0);
        for (const d of data) { const f = d ^ r[0]; r.shift(); r.push(0); for (let j = 0; j < n; j++) r[j] ^= mul(g[j + 1], f); }
        return r;
      }
      return function (bytes) {
        let v = 1, cap = 0;
        for (; v <= 10; v++) { cap = SPEC[v].slice(1).reduce((s, [b, d]) => s + b * d, 0); if (4 + (v < 10 ? 8 : 16) + bytes.length * 8 <= cap * 8) break; }
        if (v > 10) throw new Error('too long for a QR code here');
        // data bits
        const bits = [], put = (x, n) => { for (let i = n - 1; i >= 0; i--) bits.push((x >>> i) & 1); };
        put(4, 4); put(bytes.length, v < 10 ? 8 : 16); for (const b of bytes) put(b, 8);
        put(0, Math.min(4, cap * 8 - bits.length)); while (bits.length % 8) bits.push(0);
        const data = []; for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => a * 2 + b, 0));
        for (let p = 0; data.length < cap; p++) data.push(p % 2 ? 0x11 : 0xEC);
        // blocks, then interleaved
        const ec = SPEC[v][0], blocks = []; let at = 0;
        for (const [nb, nd] of SPEC[v].slice(1)) for (let k = 0; k < nb; k++) { const d = data.slice(at, at + nd); at += nd; blocks.push([d, rs(d, ec)]); }
        const out = [], maxD = Math.max(...blocks.map(b => b[0].length));
        for (let i = 0; i < maxD; i++) for (const b of blocks) if (i < b[0].length) out.push(b[0][i]);
        for (let i = 0; i < ec; i++) for (const b of blocks) out.push(b[1][i]);
        // the grid
        const N = 17 + 4 * v, M = [], F = [];
        for (let y = 0; y < N; y++) { M.push(new Array(N).fill(false)); F.push(new Array(N).fill(false)); }
        const set = (x, y, d) => { M[y][x] = d; F[y][x] = true; };
        for (let i = 0; i < N; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
        const finder = (cx, cy) => { for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) { const x = cx + dx, y = cy + dy;
          if (x < 0 || y < 0 || x >= N || y >= N) continue; const d = Math.max(Math.abs(dx), Math.abs(dy)); set(x, y, d !== 2 && d !== 4); } };
        finder(3, 3); finder(N - 4, 3); finder(3, N - 4);
        const al = ALIGN[v];
        for (const ay of al) for (const ax of al) {
          if ((ax === 6 && ay === 6) || (ax === 6 && ay === al[al.length - 1]) || (ay === 6 && ax === al[al.length - 1])) continue;
          for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
        const fmtBits = mask => { let d = mask, r = d; for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537); return ((d << 10) | r) ^ 0x5412; };   // level M = 00
        const drawFormat = mask => { const b = fmtBits(mask), bit = i => ((b >>> i) & 1) === 1;
          for (let i = 0; i <= 5; i++) set(8, i, bit(i));
          set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
          for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
          for (let i = 0; i < 8; i++) set(N - 1 - i, 8, bit(i));
          for (let i = 8; i < 15; i++) set(8, N - 15 + i, bit(i));
          set(8, N - 8, true); };
        drawFormat(0);
        if (v >= 7) { let r = v; for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1F25); const b = (v << 12) | r;
          for (let i = 0; i < 18; i++) { const d = ((b >>> i) & 1) === 1, a = N - 11 + i % 3, c = Math.floor(i / 3); set(a, c, d); set(c, a, d); } }
        // codewords, zig-zag from the bottom right
        let i = 0;
        for (let right = N - 1; right >= 1; right -= 2) {
          if (right === 6) right = 5;
          for (let vert = 0; vert < N; vert++) for (let j = 0; j < 2; j++) {
            const x = right - j, up = ((right + 1) & 2) === 0, y = up ? N - 1 - vert : vert;
            if (!F[y][x] && i < out.length * 8) { M[y][x] = ((out[i >>> 3] >>> (7 - (i & 7))) & 1) === 1; i++; }
          }
        }
        const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x, y) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
          (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => x * y % 2 + x * y % 3 === 0,
          (x, y) => (x * y % 2 + x * y % 3) % 2 === 0, (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0];
        const flip = m => { for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (!F[y][x] && MASKS[m](x, y)) M[y][x] = !M[y][x]; };
        const penalty = () => {                                // runs, 2x2 blocks and balance (enough to pick a mask)
          let p = 0, dark = 0;
          for (let a = 0; a < N; a++) for (const row of [true, false]) { let run = 1;
            for (let b = 1; b < N; b++) { const c = row ? M[a][b] : M[b][a], q = row ? M[a][b - 1] : M[b - 1][a];
              if (c === q) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1; } }
          for (let y = 0; y < N - 1; y++) for (let x = 0; x < N - 1; x++) { const c = M[y][x]; if (c === M[y][x + 1] && c === M[y + 1][x] && c === M[y + 1][x + 1]) p += 3; }
          for (const r of M) for (const c of r) if (c) dark++;
          return p + Math.floor(Math.abs(dark * 20 - N * N * 10) / (N * N)) * 10;
        };
        let best = 0, bestP = Infinity;
        for (let m = 0; m < 8; m++) { flip(m); drawFormat(m); const p = penalty(); if (p < bestP) { bestP = p; best = m; } flip(m); }
        flip(best); drawFormat(best);
        return M;
      };
    })();
    function qrCanvas(text, px) {
      const M = qrMatrix(new TextEncoder().encode(text)), N = M.length, q = 4, s = Math.max(2, Math.floor(px / (N + 2 * q)));
      const c = document.createElement('canvas'); c.width = c.height = (N + 2 * q) * s;
      const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#000';
      for (let y = 0; y < N; y++) for (let z = 0; z < N; z++) if (M[y][z]) x.fillRect((z + q) * s, (y + q) * s, s, s);
      return c;
    }

    // ── Cloud saves (relay/cloud.py): the saves follow the player with a passphrase ──────
    // The passphrase (a made-up code MC3-XXXX-..., or the player's own, 12+ characters) never
    // leaves the page: PBKDF2 turns it into a locker id, an AES-GCM key and a write token, and
    // the host keeps only the encrypted .zip. It can also be kept as a passkey (the passkey's
    // user handle holds it; signing in with the passkey gives it back) or as a QR code of a
    // link (#cloud=<code>) for another device.
    // What goes up: the newest of the page's own save backups (mc3saves, mc3/backups/), made
    // before the game starts -- so a save is never read while the game writes it, except on
    // "Upload now", which reads them like Download does. Coming down, the saves are staged
    // (mc3saves.stage) and put in place at the next start, never while the game runs.
    const CLOUD = {
      code: lsGet('mc3.cloud'), keys: null, state: '', busy: false, info: null, err: '', show: false, qr: false,
      synced: parseFloat(lsGet('mc3.cloud.synced')) || 0, last: lsGet('mc3.cloud.last'),
    };
    const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
    function newCode() { const a = new Uint8Array(20); crypto.getRandomValues(a);
      let s = ''; for (const b of a) s += B32[b & 31]; return 'MC3-' + s.match(/.{4}/g).join('-'); }
    const normCode = s => { s = String(s || '').trim(); return /^mc3-?([0-9a-z]{4}-?){5}$/i.test(s) ? 'MC3-' + s.toUpperCase().replace(/^MC3-?/, '').replace(/-/g, '').match(/.{4}/g).join('-') : s; };
    async function cloudKeys(code) {
      const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(code), 'PBKDF2', false, ['deriveBits']);
      const bits = new Uint8Array(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: new TextEncoder().encode('mc3-cloud-v1'), iterations: 150000 }, base, 768));
      const hx = b => Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
      return { id: hx(bits.slice(0, 32)), aes: await crypto.subtle.importKey('raw', bits.slice(32, 64), 'AES-GCM', false, ['encrypt', 'decrypt']), write: hx(bits.slice(64, 96)) };
    }
    const HTTP = RELAY.replace(/^ws/, 'http');
    async function keys() { if (!CLOUD.keys) CLOUD.keys = await cloudKeys(CLOUD.code); return CLOUD.keys; }
    async function cloudInfo() {
      const k = await keys(), r = await fetch(HTTP + '/cloud/' + k.id + '/info', { cache: 'no-store' });
      CLOUD.info = r.status === 404 ? { none: true } : r.ok ? await r.json() : null; return CLOUD.info;
    }
    async function newestBackup() {
      const S2 = window.mc3saves; if (!S2) throw new Error('saves are not available on this page');
      try { await S2.backupNow('cloud'); } catch (_) {}            // a backup only if they changed
      const bs = await S2.backups(); if (!bs.length) return null;
      const d = await (await (await navigator.storage.getDirectory()).getDirectoryHandle('mc3')).getDirectoryHandle('backups');
      return { name: bs[0].name, file: await (await d.getFileHandle(bs[0].name)).getFile() };
    }
    async function cloudUpload(force) {
      if (!CLOUD.code || CLOUD.busy) return;
      CLOUD.busy = true; CLOUD.err = ''; renderPanel();
      try {
        const b = await newestBackup();
        if (!b) { CLOUD.state = 'No saves on this device yet: nothing to upload.'; return; }
        if (!force && b.name === CLOUD.last) return;                // already up
        const info = await cloudInfo();
        if (info && !info.none && info.t > CLOUD.synced + 1 && !force) {
          CLOUD.state = 'The cloud has newer saves (' + new Date(info.t * 1000).toLocaleString() + ') from another device: restore them, or Upload now to replace them.';
          return;
        }
        if (info && !info.none && info.t > CLOUD.synced + 1 && force &&
            !confirm('The cloud has saves from ' + new Date(info.t * 1000).toLocaleString() + ' made on another device.\nReplace them with this device\'s saves?')) return;
        const k = await keys(), iv = crypto.getRandomValues(new Uint8Array(12));
        const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, k.aes, await b.file.arrayBuffer()));
        const r = await fetch(HTTP + '/cloud/' + k.id, { method: 'PUT', body: new Blob([new TextEncoder().encode('MC3C'), iv, ct]), headers: { 'X-Cloud-Write': k.write } });
        if (!r.ok) throw new Error(r.status === 403 ? 'this passphrase\'s locker belongs to someone else (try another passphrase)' : (await r.text()) || ('error ' + r.status));
        const j = await r.json();
        CLOUD.synced = j.t; CLOUD.last = b.name; lsSet('mc3.cloud.synced', String(j.t)); lsSet('mc3.cloud.last', b.name);
        CLOUD.state = 'Uploaded ' + Math.round(b.file.size / 1024) + ' KB, ' + new Date(j.t * 1000).toLocaleString() + '.';
        log('[SAVES] cloud upload ' + b.name);
      } catch (e) { CLOUD.err = 'Cloud upload: ' + (e && e.message || e); }
      finally { CLOUD.busy = false; renderPanel(); }
    }
    async function cloudRestore() {
      if (!CLOUD.code || CLOUD.busy) return;
      CLOUD.busy = true; CLOUD.err = ''; renderPanel();
      try {
        const k = await keys(), r = await fetch(HTTP + '/cloud/' + k.id, { cache: 'no-store' });
        if (r.status === 404) { CLOUD.state = 'Nothing in the cloud for this passphrase yet.'; return; }
        if (!r.ok) throw new Error('error ' + r.status);
        const t = parseFloat(r.headers.get('X-Cloud-Time')) || 0, buf = new Uint8Array(await r.arrayBuffer());
        let zip;
        try { zip = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf.slice(4, 16) }, k.aes, buf.slice(16)); }
        catch (_) { throw new Error('could not open them with this passphrase'); }
        const blob = new Blob([zip], { type: 'application/zip' });
        await mc3saves.stage(blob);                                   // checked, put in place at the next start
        CLOUD.synced = t; lsSet('mc3.cloud.synced', String(t)); CLOUD.last = ''; lsSet('mc3.cloud.last', '');
        const live = typeof running !== 'undefined' && running;
        if (live) {
          if (confirm('Cloud saves from ' + new Date(t * 1000).toLocaleString() + ' will replace this browser\'s saves (a backup of these is kept).\n\nThe game restarts to load them. Continue?')) location.reload();
          else { try { await (await (await navigator.storage.getDirectory()).getDirectoryHandle('mc3')).removeEntry('pending-saves.zip'); } catch (_) {} CLOUD.state = 'Nothing changed.'; }
        } else CLOUD.state = 'Cloud saves from ' + new Date(t * 1000).toLocaleString() + ' will be put in place when the game starts.';
        log('[SAVES] cloud restore staged');
      } catch (e) { CLOUD.err = 'Cloud restore: ' + (e && e.message || e); }
      finally { CLOUD.busy = false; renderPanel(); }
    }
    async function cloudUse(code, fresh) {
      code = normCode(code);
      if (!code || (code.length < 12)) { CLOUD.err = 'A passphrase needs at least 12 characters (or use a made-up code).'; renderPanel(); return; }
      CLOUD.code = code; CLOUD.keys = null; CLOUD.synced = 0; CLOUD.last = ''; CLOUD.err = ''; CLOUD.show = fresh;
      lsSet('mc3.cloud', code); lsSet('mc3.cloud.synced', '0'); lsSet('mc3.cloud.last', '');
      CLOUD.busy = true; renderPanel();
      try { await cloudInfo(); } catch (e) { CLOUD.err = String(e && e.message || e); }
      CLOUD.busy = false;
      if (CLOUD.info && !CLOUD.info.none) CLOUD.state = 'Saves found in the cloud from ' + new Date(CLOUD.info.t * 1000).toLocaleString() + '. Restore them to play with them here.';
      else { CLOUD.state = fresh ? 'Keep this code safe: it is the only way to your cloud saves. Uploading…' : 'New, empty locker. Uploading this device\'s saves…'; cloudUpload(false); }
      renderPanel();
    }
    function cloudOff() {
      if (!confirm('Stop cloud saves on this device? (Your cloud saves stay in the cloud; you need your code to get them back.)')) return;
      CLOUD.code = ''; CLOUD.keys = null; CLOUD.info = null; CLOUD.state = ''; lsSet('mc3.cloud', ''); renderPanel();
    }
    // a passkey holding the passphrase (its user handle): the browser / phone keeps it, synced
    // with the player's other devices by their password manager
    async function passkeySave() {
      try {
        const id = new TextEncoder().encode(CLOUD.code); if (id.length > 64) throw new Error('passphrase too long for a passkey (64 bytes)');
        await navigator.credentials.create({ publicKey: { rp: { name: 'MC3 Web', id: location.hostname }, user: { id, name: 'MC3 cloud saves', displayName: 'MC3 cloud saves' },
          challenge: crypto.getRandomValues(new Uint8Array(16)), pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
          authenticatorSelection: { residentKey: 'required', userVerification: 'preferred' }, timeout: 120000 } });
        CLOUD.state = 'Saved as a passkey. On another device: Sign in with passkey.';
      } catch (e) { CLOUD.err = 'Passkey: ' + (e && e.message || e); }
      renderPanel();
    }
    async function passkeyUse() {
      try {
        const c = await navigator.credentials.get({ publicKey: { challenge: crypto.getRandomValues(new Uint8Array(16)), rpId: location.hostname, userVerification: 'preferred', timeout: 120000 } });
        const code = c && c.response && c.response.userHandle ? new TextDecoder().decode(c.response.userHandle) : '';
        if (!code) throw new Error('that passkey holds no cloud saves');
        await cloudUse(code, false);
      } catch (e) { CLOUD.err = 'Passkey: ' + (e && e.message || e); renderPanel(); }
    }
    // a link from a QR code (#cloud=<code>): offered, then taken out of the address bar
    { const m = location.hash.match(/[#&]cloud=([^&]+)/);
      if (m) { const code = decodeURIComponent(m[1]); history.replaceState(null, '', location.pathname + location.search);
        setTimeout(() => { if (confirm('Use the cloud saves code from this link on this device?')) cloudUse(code, false); }, 1500); } }
    // automatic: once the page's start-of-game backup is made, and every 10 minutes
    if (CLOUD.code) { setTimeout(() => cloudUpload(false), 25000); setInterval(() => cloudUpload(false), 600000); }
    function cloudHtml() {
      let h = '<h3 class="sec">CLOUD SAVES</h3>';
      if (!CLOUD.code) {
        h += '<div class="dim">Keep your saves in the cloud and play them on any device or browser.</div>' +
             '<div class="row"><button data-op="cnew">Make me a code</button>' + (window.PublicKeyCredential ? '<button data-op="cpk">Sign in with passkey</button>' : '') + '</div>' +
             '<div class="row"><input id="sxCode" placeholder="Your code or passphrase" style="flex:1;min-width:0" autocomplete="off" spellcheck="false"><button data-op="cuse">Use</button></div>';
      } else {
        const shown = CLOUD.show ? esc(CLOUD.code) : esc(CLOUD.code.slice(0, 5)) + '••••••••';
        h += '<div class="row"><span>Code:</span><b style="font-family:Consolas,monospace;letter-spacing:1px;user-select:all">' + shown + '</b><button data-op="cshow">' + (CLOUD.show ? 'Hide' : 'Show') + '</button></div>' +
             '<div class="row"><button data-op="cup"' + (CLOUD.busy ? ' disabled' : '') + '>Upload now</button><button data-op="cdown"' + (CLOUD.busy ? ' disabled' : '') + '>Restore from cloud</button></div>' +
             '<div class="row">' + (window.PublicKeyCredential ? '<button data-op="cpksave">Save as passkey</button>' : '') + '<button data-op="cqr">' + (CLOUD.qr ? 'Hide QR' : 'QR code') + '</button><button data-op="coff">Turn off here</button></div>';
        if (CLOUD.qr) h += '<div id="sxQr" style="text-align:center;margin:6px 0"></div><div class="dim">Scan it with the other device\'s camera: the link opens the game with this code.</div>';
        if (CLOUD.synced) h += '<div class="dim">Last sync ' + new Date(CLOUD.synced * 1000).toLocaleString() + '</div>';
      }
      if (CLOUD.busy) h += '<div class="dim">Working…</div>';
      if (CLOUD.state) h += '<div class="note">' + esc(CLOUD.state) + '</div>';
      if (CLOUD.err) h += '<div class="note err">' + esc(CLOUD.err) + '</div>';
      return h;
    }
    function cloudAfterRender() {
      const q = panel.querySelector('#sxQr');
      if (q && CLOUD.code) { try { q.appendChild(qrCanvas(location.origin + '/#cloud=' + encodeURIComponent(CLOUD.code), 220)); } catch (e) { q.textContent = String(e.message || e); } }
    }
    function cloudClick(op) {
      if (op === 'cnew') cloudUse(newCode(), true);
      else if (op === 'cuse') { const v = panel.querySelector('#sxCode').value; cloudUse(v, false); }
      else if (op === 'cpk') passkeyUse();
      else if (op === 'cpksave') passkeySave();
      else if (op === 'cshow') { CLOUD.show = !CLOUD.show; renderPanel(); }
      else if (op === 'cqr') { CLOUD.qr = !CLOUD.qr; renderPanel(); }
      else if (op === 'cup') cloudUpload(true);
      else if (op === 'cdown') cloudRestore();
      else if (op === 'coff') cloudOff();
      else return false;
      return true;
    }
    S.cloud = { state: CLOUD, upload: cloudUpload, restore: cloudRestore, use: cloudUse, keys: cloudKeys, qrMatrix };

    connect();
    log('[SOCIAL] player ' + pid.slice(0, 8) + (slot ? ' (player ' + (slot + 1) + ' in this browser)' : '') + ' · chat T · talk N');
  }
})();

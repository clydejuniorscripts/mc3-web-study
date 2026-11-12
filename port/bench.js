// Paste into the page (after Play) to drive into the first Career race and measure.
// Results are only valid when "focus: yes": a window in front of the app moves it
// to efficiency cores (8 fps instead of 24 on this laptop).
window.hiddenSeen = 0;
document.addEventListener('visibilitychange', () => { if (document.hidden) hiddenSeen++; });
window.blurSeen = 0;
addEventListener('blur', () => blurSeen++);
window.sleep = ms => new Promise(r => setTimeout(r, ms));
window.tap = function (code, ms) {
  dispatchEvent(new KeyboardEvent('keydown', { code, key: code }));
  return new Promise(r => setTimeout(() => { dispatchEvent(new KeyboardEvent('keyup', { code, key: code })); r(); }, ms || 200));
};
window.lastDraws = function () {
  const l = mc3log.filter(x => /\[perf\] GL \d+ frames/.test(x)).slice(-1)[0] || '';
  const m = l.match(/per frame: (\d+) draws/);
  return m ? +m[1] : 0;
};
window.toRace = async function () {
  for (let i = 0; i < 6; i++) { await tap('KeyP', 300); await sleep(3000); }
  await tap('Space', 300); await sleep(4000);     // Career
  await tap('Space', 300); await sleep(12000);    // Start Career
  await tap('Space', 300); await sleep(10000);
  for (let i = 0; i < 40 && lastDraws() < 1000; i++) { if (i % 10 === 9) await tap('Space', 300); await sleep(1000); }
  return lastDraws();
};
window.bench = async function (secs) {
  const h0 = hiddenSeen, b0 = blurSeen, n0 = mc3log.length;
  dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
  await sleep(secs * 1000);
  dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyW' }));
  const s = mc3log.slice(n0);
  const ok = !(hiddenSeen - h0) && !document.hidden && !(blurSeen - b0) && document.hasFocus();
  return 'valid (visible and in front): ' + (ok ? 'yes' : 'NO') + '\n' +
    s.filter(l => /\[perf\] (main loop|GL \d+ frames|main thread:|GL thread)/.test(l)).slice(-4).map(l => l.slice(0, 300)).join('\n');
};
'helpers ready';

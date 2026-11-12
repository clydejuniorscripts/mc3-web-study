// Runs in the page and in every worker (pthread). A trap inside a worker's
// requestAnimationFrame callback (the GL thread) reaches the page as a bare
// message; print its stack from inside the worker first.
if (typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope) {
  self.addEventListener('error', (e) => {
    try {
      var s = (e && e.error && e.error.stack) ? e.error.stack : String(e && e.message);
      err('[worker error] ' + s);
    } catch (_) {}
  });
}

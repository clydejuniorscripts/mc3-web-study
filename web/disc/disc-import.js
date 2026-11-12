/* disc-import.js — Web Worker: import an Xbox MC3 disc image into OPFS.
 *
 * Reads the image lazily with Blob.slice (never loads the whole 7 GB), walks
 * XDVDFS (via disc-core.js), streams every file into OPFS under /mc3/game/<path>,
 * writes /mc3/game_manifest.txt (path<TAB>size per line), and validates
 * default.xbe so only MC3: DUB Edition USA (title ID 0x54540079) is accepted.
 *
 * Load as a module worker:
 *   const w = new Worker('disc/disc-import.js', { type: 'module' });
 *   w.postMessage({ type: 'import', file });   // file: File from <input type=file>
 *   w.postMessage({ type: 'import', url });    // development: a Range-capable same-origin URL
 * Messages out:
 *   { type:'progress', phase:'scan'|'copy', done, total, path }
 *   { type:'done', manifest, files, bytes, title:{id,name} }
 *   { type:'error', message }
 */
import { SECTOR, WANT_TITLE_ID, CHUNK, findBase, listFiles, checkXbe } from "./disc-core.js";

function fileReader(file) {
  return {
    size: file.size,
    async readAt(off, len) {
      return new DataView(await file.slice(off, off + len).arrayBuffer());
    },
  };
}

async function opfsDir(root, path) {
  let dir = root;
  for (const part of path.split("/")) if (part) dir = await dir.getDirectoryHandle(part, { create: true });
  return dir;
}

async function streamToOpfs(root, file, outPath, absStart, size, onChunk) {
  const slash = outPath.lastIndexOf("/");
  const dir = await opfsDir(root, slash >= 0 ? outPath.slice(0, slash) : "");
  const name = slash >= 0 ? outPath.slice(slash + 1) : outPath;
  const fh = await dir.getFileHandle(name, { create: true });
  const ah = await fh.createSyncAccessHandle();
  try {
    ah.truncate(0);
    for (let off = 0; off < size; ) {
      const n = Math.min(CHUNK, size - off);
      const buf = await file.slice(absStart + off, absStart + off + n).arrayBuffer();
      ah.write(new Uint8Array(buf), { at: off });
      off += n;
      onChunk(n);
    }
    ah.flush();
  } finally { ah.close(); }
}

async function readOpfs(root, path) {
  const slash = path.lastIndexOf("/");
  const dir = await opfsDir(root, slash >= 0 ? path.slice(0, slash) : "");
  const fh = await dir.getFileHandle(path.slice(slash + 1));
  return await (await fh.getFile()).arrayBuffer();
}
async function writeText(root, path, text) {
  const slash = path.lastIndexOf("/");
  const dir = await opfsDir(root, slash >= 0 ? path.slice(0, slash) : "");
  const fh = await dir.getFileHandle(path.slice(slash + 1), { create: true });
  const ah = await fh.createSyncAccessHandle();
  ah.truncate(0); ah.write(new TextEncoder().encode(text), { at: 0 }); ah.flush(); ah.close();
}
const toHex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function importDisc(file, post) {
  if (!navigator.storage || !navigator.storage.getDirectory)
    throw new Error("This browser has no OPFS (origin-private file system).");

  post({ type: "progress", phase: "scan", done: 0, total: 1, path: "reading disc layout…" });
  const reader = fileReader(file);
  const base = await findBase(reader);
  const files = await listFiles(reader, base);
  if (!files.length) throw new Error("No files found in the disc image.");
  if (!files.some(f => f.path.toLowerCase() === "default.xbe"))
    throw new Error("No default.xbe — this is not a bootable Xbox game disc.");

  const totalBytes = files.reduce((a, f) => a + f.size, 0);
  try { await navigator.storage.persist(); } catch (_) {}
  const root = await navigator.storage.getDirectory();

  let done = 0;
  const manifest = [];
  for (const f of files) {
    post({ type: "progress", phase: "copy", done, total: totalBytes, path: f.path });
    try {
      await streamToOpfs(root, file, "mc3/game/" + f.path, base + f.startSector * SECTOR, f.size,
        (n) => { done += n; });
    } catch (err) {
      const s = String(err && err.name) + " " + String(err && err.message);
      if (/quota|space/i.test(s))
        throw new Error("Out of browser storage writing " + f.path + " — free space or allow more, then retry. (" + err.message + ")");
      throw new Error("Failed writing " + f.path + ": " + (err && err.message || err));
    }
    manifest.push(f.path + "\t" + f.size);
  }

  const xbeBuf = await readOpfs(root, "mc3/game/default.xbe");
  const info = checkXbe(xbeBuf);
  if (info.titleId !== WANT_TITLE_ID)
    throw new Error("Wrong game/edition: default.xbe title ID 0x" + info.titleId.toString(16) +
      " (\"" + info.name + "\"). This build needs MC3: DUB Edition USA (0x54540079).");

  const manText = manifest.join("\n") + "\n";
  await writeText(root, "mc3/game_manifest.txt", manText);

  // Sentinel, written LAST: its presence means the import finished and is the
  // right disc. The game can read this instead of re-hashing 3.4 GB.
  const disc = {
    titleId: "0x" + info.titleId.toString(16),
    version: info.version,
    xbeSha256: toHex(await crypto.subtle.digest("SHA-256", xbeBuf)),
    files: files.length,
    bytes: totalBytes,
    importedAt: new Date().toISOString(),
  };
  await writeText(root, "mc3/disc.json", JSON.stringify(disc, null, 2) + "\n");

  post({ type: "done", manifest: manText, files: files.length, bytes: totalBytes,
         title: { id: disc.titleId, name: info.name, version: info.version }, disc });
}

/* Development: the image from a same-origin URL with Range requests (the dev
 * server's /dev/disc.iso), shaped like a File for importDisc. A page cannot
 * hand a local file to automation, so this is how the importer is tested
 * end to end. */
async function urlFile(url) {
  const head = await fetch(url, { method: "HEAD" });
  const size = Number(head.headers.get("Content-Length"));
  if (!head.ok || !size) throw new Error("Cannot read " + url + " (HTTP " + head.status + ")");
  return {
    size,
    slice(a, b) {
      return { arrayBuffer: async () => {
        const r = await fetch(url, { headers: { Range: "bytes=" + a + "-" + (b - 1) } });
        if (r.status !== 206 && r.status !== 200) throw new Error("Range read failed: HTTP " + r.status);
        return r.arrayBuffer();
      } };
    },
  };
}

self.onmessage = async (e) => {
  const m = e.data || {};
  if (m.type !== "import" || !(m.file || m.url)) return;
  try { await importDisc(m.file || await urlFile(m.url), (x) => self.postMessage(x)); }
  catch (err) { self.postMessage({ type: "error", message: (err && err.message) || String(err) }); }
};

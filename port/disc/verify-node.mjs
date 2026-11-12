/* verify-node.mjs — test disc-core.js against a real ISO in Node (no browser).
 * Proves the XDVDFS walk is byte-accurate and the default.xbe check works.
 *
 *   node verify-node.mjs "<path to .iso>"
 *
 * Prints the file count, the default.xbe title/ID check, and SHA-256 of a
 * >2 MB and a <2 MB file (compare against  sha256sum ~/mc3-web/game/<path>).
 */
import * as fs from "node:fs";
import { createHash } from "node:crypto";
import { findBase, listFiles, checkXbe, SECTOR } from "./disc-core.js";

const ISO = process.argv[2];   // your own disc image: node verify-node.mjs <path to .iso>
if (!ISO) { console.error("usage: node verify-node.mjs <your disc image .iso>"); process.exit(1); }

const fd = fs.openSync(ISO, "r");
const size = fs.fstatSync(fd).size;

function readSync(off, len) {
  const b = Buffer.allocUnsafe(len);
  let got = 0;
  while (got < len) {
    const n = fs.readSync(fd, b, got, len - got, off + got);
    if (n <= 0) break;
    got += n;
  }
  return b;
}
const reader = { size, async readAt(off, len) {
  const b = readSync(off, len);
  return new DataView(b.buffer, b.byteOffset, b.byteLength);
} };

function sha256(f) {
  const h = createHash("sha256");
  const CH = 8 << 20;
  for (let off = 0; off < f.size; ) {
    const n = Math.min(CH, f.size - off);
    h.update(readSync(base + f.startSector * SECTOR + off, n));
    off += n;
  }
  return h.digest("hex");
}

console.log(`ISO: ${ISO}\nsize: ${(size / 1073741824).toFixed(2)} GB`);
const base = await findBase(reader);
const files = await listFiles(reader, base);
const total = files.reduce((a, f) => a + f.size, 0);
console.log(`base=0x${base.toString(16)}  files=${files.length}  totalData=${(total / 1048576).toFixed(1)} MB`);

const xbe = files.find(f => f.path.toLowerCase() === "default.xbe");
if (!xbe) { console.log("NO default.xbe — not a game disc"); process.exit(1); }
const xbeBuf = readSync(base + xbe.startSector * SECTOR, xbe.size);
const info = checkXbe(xbeBuf.buffer.slice(xbeBuf.byteOffset, xbeBuf.byteOffset + xbe.size));
console.log(`default.xbe: title="${info.name}"  id=0x${info.titleId.toString(16)}  version=${info.version}  ` +
  (info.titleId === 0x54540079 ? "=> ACCEPT (USA)" : "=> REJECT (wrong edition)"));

const big = xbe;  // 4.87 MB, > 2 MB
const mid = files.filter(f => f.size >= 1048576 && f.size < 2 * 1048576).sort((a, b) => a.size - b.size)[0];
const small = files.filter(f => f.size > 0 && f.size < 1048576).sort((a, b) => a.size - b.size)[0];
console.log("\nsha256 (compare vs  sha256sum ~/mc3-web/game/<path>):");
for (const f of [big, mid, small].filter(Boolean))
  console.log(`  ${sha256(f)}  ${f.size}\t${f.path}`);

console.log("\ndisc.json (the sentinel the worker writes last):");
console.log(JSON.stringify({
  titleId: "0x" + info.titleId.toString(16),
  version: info.version,
  xbeSha256: sha256(xbe),
  files: files.length,
  bytes: total,
  importedAt: new Date().toISOString(),
}, null, 2));

fs.closeSync(fd);

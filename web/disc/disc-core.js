/* disc-core.js — pure Xbox XDVDFS parsing, shared by the worker (browser/OPFS)
 * and the Node verifier. No DOM, no OPFS: it takes a `reader` abstraction so the
 * same code runs in a Web Worker (File.slice) and in Node (fs).
 *
 *   reader = { size: number, readAt(off, len) -> Promise<DataView> }
 *
 * Layouts handled:
 *   - plain XISO:       XDVDFS volume magic at 0x10000     (partition base 0)
 *   - Redump full dump: magic at 0x18310000  (game partition base 0x18300000)
 */
export const SECTOR = 2048;
export const XDVDFS_MAGIC = "MICROSOFT*XBOX*MEDIA";
export const REDUMP_BASE = 0x18300000;
export const WANT_TITLE_ID = 0x54540079;   // Midnight Club 3: DUB Edition, USA
export const CHUNK = 8 << 20;

const td = new TextDecoder("latin1");
function str(dv, off, len) {
  return td.decode(new Uint8Array(dv.buffer, dv.byteOffset + off, len));
}

/* Locate the XDVDFS volume; returns the partition base offset. */
export async function findBase(reader) {
  for (const base of [0, REDUMP_BASE]) {
    if (base + 0x10000 + 32 > reader.size) continue;
    const dv = await reader.readAt(base + 0x10000, 32);
    if (str(dv, 0, XDVDFS_MAGIC.length) === XDVDFS_MAGIC) return base;
  }
  throw new Error(
    "Not an Xbox disc image (no XDVDFS volume at 0x10000 or 0x18310000). " +
    "Expected a plain XISO or a Redump-layout dump.");
}

/* Read one directory's entries. The directory is a binary tree packed into its
 * sectors; left/right are offsets in 4-byte units from the extent start. */
async function readDir(reader, base, sector, size) {
  const bytes = new Uint8Array(size);
  let got = 0;
  while (got < size) {
    const n = Math.min(CHUNK, size - got);
    const dv = await reader.readAt(base + sector * SECTOR + got, n);
    bytes.set(new Uint8Array(dv.buffer, dv.byteOffset, n), got);
    got += n;
  }
  const dv = new DataView(bytes.buffer);
  const out = [];
  const seen = new Set();
  const stack = [0];
  while (stack.length) {
    const o = stack.pop();
    if (seen.has(o)) continue;
    seen.add(o);
    const p = o * 4;
    if (p + 14 > size) continue;
    const left = dv.getUint16(p, true);
    const right = dv.getUint16(p + 2, true);
    const startSector = dv.getUint32(p + 4, true);
    const fileSize = dv.getUint32(p + 8, true);
    const attr = dv.getUint8(p + 12);
    const nlen = dv.getUint8(p + 13);
    if (p + 14 + nlen > size) continue;
    out.push({ name: str(dv, p + 14, nlen), startSector, size: fileSize,
               isDir: (attr & 0x10) !== 0 });
    if (left && left !== 0xffff) stack.push(left);
    if (right && right !== 0xffff) stack.push(right);
  }
  return out;
}

/* Every file in the image as { path, startSector, size } (dirs expanded). */
export async function listFiles(reader, base) {
  const dv = await reader.readAt(base + 0x10000, 0x20);
  const rootSector = dv.getUint32(0x14, true);
  const rootSize = dv.getUint32(0x18, true);
  const files = [];
  async function recurse(sector, size, prefix) {
    for (const e of await readDir(reader, base, sector, size)) {
      if (!e.name || e.name === "." || e.name === "..") continue;
      const path = prefix ? prefix + "/" + e.name : e.name;
      if (e.isDir) { if (e.size > 0) await recurse(e.startSector, e.size, path); }
      else files.push({ path, startSector: e.startSector, size: e.size });
    }
  }
  await recurse(rootSector, rootSize, "");
  return files;
}

/* Parse a default.xbe ArrayBuffer -> { titleId, name, version }.
 * XBE certificate: titleId @0x08, wszTitleName[40] @0x0C (80 bytes),
 * altTitleIds[16] @0x5C, allowedMedia 0x9C, region 0xA0, ratings 0xA4,
 * diskNumber 0xA8, version @0xAC. */
export function checkXbe(buf) {
  const dv = new DataView(buf);
  if (str(dv, 0, 4) !== "XBEH") throw new Error("default.xbe is not a valid XBE (no XBEH magic).");
  const base = dv.getUint32(0x104, true);
  const certVa = dv.getUint32(0x118, true);
  const certOff = certVa - base;
  if (certOff < 0 || certOff + 0xb0 > buf.byteLength) throw new Error("default.xbe certificate out of range.");
  const titleId = dv.getUint32(certOff + 0x08, true);
  let name = "";
  for (let i = 0; i < 80; i += 2) {
    const c = dv.getUint16(certOff + 0x0c + i, true);
    if (c === 0) break;
    name += String.fromCharCode(c);
  }
  const version = dv.getUint32(certOff + 0xac, true);
  return { titleId, name, version };
}

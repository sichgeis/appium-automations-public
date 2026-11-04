// Technical preparation. Research, downloaded originals and image mappings stay private.
import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { isIP } from 'node:net';
import sharp from 'sharp';
import { sealImage, openImage } from './web/catalog.mjs';

const [directory, research] = process.argv.slice(2);
if (!directory || !research) throw new Error('Aufruf: prepare-images.mjs <privater Katalogordner> <Rechercheordner>');
const catalog = JSON.parse(await readFile(path.join(directory, 'catalog.json'), 'utf8'));
const key = new Uint8Array(await readFile(path.join(directory, 'access-key.bin')));
const known = new Set(catalog.products.map(p => p.id));
let rejected = [];
try { rejected = JSON.parse(await readFile(path.join(directory, 'image-rejections.json'), 'utf8')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
const rejectedPairs = new Set(rejected.map(r => r.id + '\n' + r.imageUrl));
const candidates = new Map();
for (const name of (await readdir(research)).filter(n => /^results-.*\.json$/.test(n)).sort()) {
  for (const row of JSON.parse(await readFile(path.join(research, name), 'utf8'))) {
    if (!known.has(row.id) || row.status !== 'matched') continue;
    if (rejectedPairs.has(row.id + '\n' + row.imageUrl)) continue;
    if (!['product', 'illustrative'].includes(row.kind) || typeof row.title !== 'string' || !row.title.trim()) continue;
    try { publicUrl(row.imageUrl); publicUrl(row.sourceUrl); } catch { continue; }
    const previous = candidates.get(row.id);
    if (!previous || (previous.kind === 'illustrative' && row.kind === 'product')) candidates.set(row.id, row);
  }
}
const registryFile = path.join(directory, 'product-images.json');
let registry = { products: {}, assets: {}, urls: {} };
try { registry = JSON.parse(await readFile(registryFile, 'utf8')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
if (Object.entries(registry.products).some(([id, image]) => rejectedPairs.has(id + '\n' + registry.assets[image.id]?.originalUrl))) {
  await writeFile(path.join(directory, 'product-images.before-visual-review.json'), JSON.stringify(registry, null, 2), { mode: 0o600 });
  for (const [id, image] of Object.entries(registry.products)) {
    if (rejectedPairs.has(id + '\n' + registry.assets[image.id]?.originalUrl)) delete registry.products[id];
  }
}
await mkdir(path.join(directory, 'images'), { recursive: true, mode: 0o700 });
await mkdir(path.join(directory, 'sealed-images'), { recursive: true, mode: 0o700 });
let errors = 0, downloads = 0;
const failures = [];
const pendingUrls = new Map();
for (const row of candidates.values()) {
  if (!pendingUrls.has(row.imageUrl)) pendingUrls.set(row.imageUrl, []);
  pendingUrls.get(row.imageUrl).push(row);
}
const jobs = [...pendingUrls.entries()];
let cursor = 0;
async function worker() {
  while (cursor < jobs.length) {
    const [url, rows] = jobs[cursor++];
    try {
      let asset = registry.urls[url] && registry.assets[registry.urls[url]];
      if (!asset) {
        const raw = await download(url);
        const metadata = await sharp(raw, { limitInputPixels: 40_000_000 }).metadata();
        if (!['jpeg', 'png', 'webp', 'gif'].includes(metadata.format)) throw new Error('Unsupported raster');
        const jpeg = await sharp(raw, { limitInputPixels: 40_000_000, animated: false }).rotate()
          .resize({ width: 384, height: 384, fit: 'inside', withoutEnlargement: true })
          .flatten({ background: '#ffffff' }).jpeg({ quality: 76, mozjpeg: true }).toBuffer();
        if (jpeg.length > 512 * 1024) throw new Error('Image too large');
        const id = randomUUID().replaceAll('-', '');
        const bytes = await sealImage(new Uint8Array(jpeg), key, catalog.id, id);
        const plain = await openImage(bytes, key, catalog.id, id);
        if (Buffer.compare(Buffer.from(plain), jpeg)) throw new Error('Image round trip mismatch');
        await writeFile(path.join(directory, 'images', id + '.jpg'), jpeg, { mode: 0o600 });
        await writeFile(path.join(directory, 'sealed-images', id + '.bin'), bytes, { mode: 0o600 });
        asset = { id, bytes: bytes.length, originalUrl: url };
        registry.assets[id] = asset; registry.urls[url] = id; downloads++;
      }
      for (const row of rows) {
        const image = { id: asset.id, mime: 'image/jpeg', title: row.title, sourceUrl: row.sourceUrl, kind: row.kind };
        if (typeof row.credit === 'string' && row.credit) image.credit = row.credit;
        if (typeof row.license === 'string' && row.license) image.license = row.license;
        registry.products[row.id] = image;
      }
    } catch (error) { errors += rows.length; failures.push({ ids: rows.map(r => r.id), type: error.name, reason: error.message }); }
  }
}
await Promise.all(Array.from({ length: 4 }, worker));
await writeFile(registryFile, JSON.stringify(registry, null, 2), { mode: 0o600 });
const used = new Set(Object.values(registry.products).map(p => p.id));
const result = { researchedCandidates: candidates.size, cardsWithImages: Object.keys(registry.products).filter(id => known.has(id)).length,
  downloads, failedCards: errors, uniqueImages: used.size, encryptedBytes: [...used].reduce((n, id) => n + registry.assets[id].bytes, 0) };
await writeFile(path.join(directory, 'image-preparation-summary.json'), JSON.stringify(result, null, 2), { mode: 0o600 });
await writeFile(path.join(directory, 'image-download-failures.json'), JSON.stringify(failures, null, 2), { mode: 0o600 });
process.stdout.write(JSON.stringify(result) + '\n');

function publicUrl(text) {
  const url = new URL(text);
  if (url.protocol !== 'https:' || url.username || url.password || isIP(url.hostname) || !url.hostname.includes('.')
    || /(?:^|\.)(?:localhost|local|internal)$/.test(url.hostname)) throw new Error('Not a public image URL');
  return url;
}
async function download(text) {
  let url = publicUrl(text);
  for (let hop = 0; hop < 5; hop++) {
    const response = await fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(15000), credentials: 'omit', referrerPolicy: 'no-referrer' });
    if ([301, 302, 303, 307, 308].includes(response.status)) { url = publicUrl(new URL(response.headers.get('location'), url).href); continue; }
    if (!response.ok || !/^(?:image\/(?:jpeg|png|webp|gif)|application\/octet-stream)(?:;|$)/i.test(response.headers.get('content-type') ?? '')) throw new Error(`Not a raster response (${response.status}, ${response.headers.get('content-type') ?? 'unknown'})`);
    const chunks = []; let size = 0;
    for await (const part of response.body) { size += part.byteLength; if (size > 8 * 1024 * 1024) throw new Error('Image too large'); chunks.push(part); }
    return Buffer.concat(chunks);
  }
  throw new Error('Too many redirects');
}

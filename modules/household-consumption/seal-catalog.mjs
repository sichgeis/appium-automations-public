// Technical migration only. Private key/link are written locally, never printed.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { sealCatalog, encodeKey, openCatalog } from './web/catalog.mjs';

const [input, output, base] = process.argv.slice(2);
if (!input || !output || !base) throw new Error('Aufruf: node seal-catalog.mjs <catalog.json> <privater Ausgabeordner> <App-URL>');
const target = new URL(base);
if (target.protocol !== 'https:') throw new Error('Privater Online-Start benötigt HTTPS.');
const catalog = JSON.parse(await readFile(input, 'utf8'));
const keyFile = path.join(path.dirname(input), 'access-key.bin');
let existingKey = null;
try { existingKey = await readFile(keyFile); } catch (error) { if (error.code !== 'ENOENT') throw error; }
const { bytes, key } = await sealCatalog(catalog, crypto, existingKey);
if (!existingKey) await writeFile(keyFile, key, { mode: 0o600, flag: 'wx' });
await openCatalog(bytes, key, catalog.id); // independent authenticated round trip before writing
await mkdir(path.join(output, 'sealed'), { recursive: true, mode: 0o700 });
const file = path.join(output, 'sealed', catalog.id + '.bin');
await writeFile(file, bytes, { mode: 0o600, flag: 'wx' });
target.searchParams.set('app', 'catalog-3');
target.hash = new URLSearchParams({ catalog: catalog.id, key: encodeKey(key) }).toString();
await writeFile(path.join(output, 'private-start-url.txt'), target.href + '\n', { mode: 0o600, flag: 'wx' });
await writeFile(path.join(output, 'private-start.webloc'), '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>URL</key><string>' + target.href.replaceAll('&', '&amp;') + '</string></dict></plist>', { mode: 0o600, flag: 'wx' });
// Copy candidate ciphertext to a dedicated review directory, never auto-publish it.
await writeFile(path.join(output, 'sealed-manifest.json'), JSON.stringify({ id: catalog.id, file: path.basename(file), bytes: bytes.length, format: 'HHC1/AES-256-GCM' }), { mode: 0o600, flag: 'wx' });
process.stdout.write('Verschlüsseltes Paket und privater Startlink lokal vorbereitet; nichts veröffentlicht.\n');

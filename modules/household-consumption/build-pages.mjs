import { lstat, readFile, mkdir, mkdtemp, writeFile, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const { demoPath } = JSON.parse(await readFile(path.join(moduleDir, 'pages.config.json'), 'utf8'));
if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(demoPath)) throw new Error('Ungültiger Demo-Pfad.');

// Explicit allowlist: never copy the repository, local storage, output/, or receipt files.
export const publicFiles = ['index.html', 'style.css', 'app.mjs', 'core.mjs', 'products.mjs', 'backup.mjs'];
for (const file of publicFiles) {
  if (!(await lstat(path.join(moduleDir, 'web', file))).isFile()) throw new Error(`Keine reguläre Quelldatei: ${file}`);
}
const html = await readFile(path.join(moduleDir, 'web/index.html'), 'utf8');
if (!html.includes('<meta name="robots" content="noindex, nofollow">')) throw new Error('noindex fehlt.');
const outputParent = path.resolve(moduleDir, '../../output/household-consumption');
await mkdir(outputParent, { recursive: true });
const destination = await mkdtemp(path.join(outputParent, 'pages-'));
await mkdir(path.join(destination, demoPath));
for (const file of publicFiles) await copyFile(path.join(moduleDir, 'web', file), path.join(destination, demoPath, file));
const blank = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer"><title>Demo</title></head><body><p>Bitte den vollständigen Demo-Link verwenden.</p></body></html>\n';
await writeFile(path.join(destination, 'index.html'), blank);
await writeFile(path.join(destination, '404.html'), blank);
await writeFile(path.join(destination, '.nojekyll'), '');
await writeFile(path.join(destination, 'robots.txt'), '# Index exclusion is supplied by noindex on every HTML page.\n# Do not block crawling: crawlers must be able to read noindex.\n# On project Pages, the effective robots.txt belongs at the domain root.\nUser-agent: *\nDisallow:\n');
process.stdout.write(JSON.stringify({ directory: destination, demoPath, files: publicFiles.length + 4 }) + '\n');

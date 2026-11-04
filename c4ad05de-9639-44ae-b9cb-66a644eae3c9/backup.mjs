import { validateState, initialState } from './core.mjs';

export const DATASET = 'synthetic-demo-v1';
export const RECOVERY_KEY = 'household-swipe-before-import-v1';
export const MAX_BACKUP_BYTES = 2 * 1024 * 1024;
const catalog = products => products.map(({ id, name, detail, merchant, total }) => ({ id, name, detail, merchant, total }));

export function createBackup(state, products, now = new Date()) {
  validateState(state, products);
  return {
    format: 'household-consumption-assessment', version: 1, dataset: DATASET,
    exportedAt: now.toISOString(), products: catalog(products), state: structuredClone(state),
  };
}

export function parseBackup(text, products) {
  if (new TextEncoder().encode(text).byteLength > MAX_BACKUP_BYTES) throw new Error('Die Datei ist zu groß (maximal 2 MB).');
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('Die Datei enthält kein gültiges JSON.'); }
  // Read the previous demo download format too; never silently accept another dataset.
  if (data?.dataset === DATASET && data.version === 1 && !data.format && data.decisions) {
    const legacy = validateState(data, products);
    return { ...legacy, assessment: legacy.assessment ?? initialState().assessment };
  }
  if (data?.format !== 'household-consumption-assessment' || data.version !== 1 || data.dataset !== DATASET) {
    throw new Error('Unbekanntes Dateiformat oder anderer Produktdatensatz. Der aktuelle Stand bleibt erhalten.');
  }
  const expected = catalog(products);
  if (!Array.isArray(data.products) || data.products.length !== expected.length
    || !expected.every(p => {
      const matches = data.products.filter(q => q?.id === p.id);
      return matches.length === 1 && Object.keys(p).every(k => matches[0][k] === p[k]);
    })) throw new Error('Die Produkte passen nicht zu dieser Demo. Kein Import vorgenommen.');
  const restored = validateState(data.state, products);
  if (!restored.assessment) throw new Error('Die Bewertungskennung fehlt.');
  return restored;
}

export function backupText(state, products) { return JSON.stringify(createBackup(state, products), null, 2); }
export function filename(state, extension = 'json') {
  // No personal names in filenames. Independent assessments keep distinct identities.
  return `tisch-fuer-zwei-${state.assessment.id}-${new Date().toISOString().replace(/[:.]/g, '-')}.${extension}`;
}

export function shareFile(navigatorApi, text, state) {
  if (typeof navigatorApi.share !== 'function' || typeof navigatorApi.canShare !== 'function') return null;
  // Browser support for JSON says nothing about the selected messenger's support.
  // Prefer a plain text attachment; its contents remain fully restorable JSON.
  for (const [type, ext] of [['text/plain', 'txt'], ['application/json', 'json']]) {
    const file = new File([text], filename(state, ext), { type });
    try { if (navigatorApi.canShare({ files: [file] })) return file; } catch { /* try the portable text file */ }
  }
  return null;
}

export async function handOffShare(navigatorApi, file) {
  try {
    // One item only: avoid extra text/title items competing with the attachment.
    await navigatorApi.share({ files: [file] });
    return 'handed-off';
  } catch (error) {
    if (error.name === 'AbortError') return 'cancelled';
    throw new Error('Teilen war nicht möglich. Bitte die Datei herunterladen und als Anhang verschicken.');
  }
}

export async function handOffTextShare(navigatorApi, text) {
  if (typeof navigatorApi.share !== 'function') throw new Error('Dieser Browser unterstützt das Teilen von Nachrichten nicht. Bitte die Datei herunterladen.');
  if (new TextEncoder().encode(text).byteLength > 32000) throw new Error('Diese Bewertung ist für eine Textnachricht zu groß. Bitte als Datei teilen oder herunterladen.');
  try {
    await navigatorApi.share({ text });
    return 'handed-off';
  } catch (error) {
    if (error.name === 'AbortError') return 'cancelled';
    throw new Error('Textteilen war nicht möglich. Bitte die Datei herunterladen und direkt in Signal anhängen.');
  }
}

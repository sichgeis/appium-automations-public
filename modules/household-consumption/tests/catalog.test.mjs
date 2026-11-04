import test from 'node:test';
import assert from 'node:assert/strict';
import { validateCatalog, sealCatalog, openCatalog, encodeKey, loadCatalog, catalogStorageKey } from '../web/catalog.mjs';
import { initialState, assign, persist, summary } from '../web/core.mjs';
import { createBackup, parseBackup } from '../web/backup.mjs';

const id = 'catalog-00000000-0000-4000-8000-000000000001';
function fixture(size = 1) {
  const products = Array.from({ length: size }, (_, i) => ({
    id: 'p-' + i.toString(16).padStart(24, '0'), name: 'Synthetisches Testprodukt ' + i, brand: 'Lebensmittel',
    detail: 'Synthetische Sorte', merchant: 'Testhändler', count: 1, quantity: 'Menge nicht belegt',
    total: 199, low: null, high: null, priceLabel: 'Einzelpreis laut Bon', variant: 'Identität separat prüfen',
    purchases: [{ id: 'p-' + i.toString(16).padStart(24, '0'), amount: 199, month: '2026-07' }],
  }));
  return { format: 'household-catalog', version: 1, id, synthetic: false, revision: '0'.repeat(64),
    coverage: { receipts: 1 }, ledgerTotals: { food: 199 * size }, products };
}
const memory = () => {
  const values = new Map();
  return { getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, v) };
};

test('catalog encryption round trip uses fresh keys and authenticates all contents and catalog identity', async () => {
  const catalog = fixture(); const a = await sealCatalog(catalog); const b = await sealCatalog(catalog);
  assert.deepEqual(await openCatalog(a.bytes, a.key, id), catalog);
  assert.notDeepEqual(a.bytes, b.bytes); assert.notDeepEqual(a.key, b.key);
  const updated = await sealCatalog(catalog, crypto, a.key);
  assert.deepEqual(updated.key, a.key); assert.notDeepEqual(updated.bytes, a.bytes);
  assert.deepEqual(await openCatalog(updated.bytes, a.key, id), catalog);
  assert.equal(new TextDecoder().decode(a.bytes).includes(catalog.products[0].name), false);
  const changed = a.bytes.slice(); changed[30] ^= 1;
  await assert.rejects(openCatalog(changed, a.key, id));
  await assert.rejects(openCatalog(a.bytes, b.key, id));
  await assert.rejects(openCatalog(a.bytes, a.key, id.replace(/1$/, '2')));
});
test('catalog validation rejects unexpected private metadata and incorrect purchase sums', () => {
  const catalog = fixture(); catalog.source = '/private/forbidden';
  assert.throws(() => validateCatalog(catalog)); delete catalog.source;
  catalog.products[0].total++;
  assert.throws(() => validateCatalog(catalog));
});
test('automatic link loading strips key before fetching, never transmits it and resumes without import UI', async () => {
  const catalog = fixture(); const sealed = await sealCatalog(catalog); const key = encodeKey(sealed.key);
  const storage = memory(); let stripped = false;
  const response = { ok: true, arrayBuffer: async () => sealed.bytes.buffer };
  const location = { hash: '#catalog=' + id + '&key=' + key, href: 'https://example.org/demo/#catalog=' + id + '&key=' + key, pathname: '/demo/', search: '' };
  const loaded = await loadCatalog({ location, history: { replaceState(a, b, url) { assert.equal(url.includes(key), false); stripped = true; } }, storage,
    fetcher: async (url, options) => { assert.ok(stripped); assert.equal(url.href.includes(key), false); assert.equal(url.hash, ''); assert.equal(options.credentials, 'omit'); return response; } });
  assert.equal(loaded.id, id);
  const resumed = await loadCatalog({ location: { ...location, hash: '' }, history: {}, storage, fetcher: async () => response });
  assert.equal(resumed.id, id);
});
test('failed authentication never stores access or silently substitutes demo products', async () => {
  const storage = memory(); const sealed = await sealCatalog(fixture());
  const location = { hash: '#catalog=' + id + '&key=' + encodeKey(new Uint8Array(32)), href: 'https://example.org/demo/', pathname: '/demo/', search: '' };
  await assert.rejects(loadCatalog({ location, history: { replaceState() {} }, storage, fetcher: async () => ({ ok: true, arrayBuffer: async () => sealed.bytes.buffer }) }));
  assert.equal(storage.getItem('household-last-private-catalog'), null);
});
test('demo and real assessments have isolated persistence; additive products keep previous decisions', () => {
  const storage = memory(); const catalog = fixture(); const state = assign(initialState(), catalog.products[0].id, 'a');
  storage.setItem(catalogStorageKey('synthetic-demo-v1'), 'old demo untouched');
  persist(storage, state, fixture(2).products, catalogStorageKey(id));
  assert.equal(storage.getItem(catalogStorageKey('synthetic-demo-v1')), 'old demo untouched');
  assert.deepEqual(JSON.parse(storage.getItem(catalogStorageKey(id))).decisions, state.decisions);
});
test('real money is split per purchase, including odd cents', () => {
  const p = { id: 'test', total: 398, purchases: [{ amount: 199 }, { amount: 199 }] };
  const s = summary(assign(initialState(), p.id, 'shared'), [p]);
  assert.equal(s.a, 200); assert.equal(s.b, 198);
});
test('650-card assessment fits messenger limit without product names or undo history', () => {
  const catalog = fixture(650); let state = initialState();
  for (const product of catalog.products) state = assign(state, product.id, 'shared');
  state.queue = catalog.products.map(p => p.id);
  const backup = createBackup(state, catalog.products, new Date(), id);
  const text = JSON.stringify(backup);
  assert.ok(new TextEncoder().encode(text).length < 32000);
  assert.equal(text.includes('Synthetisches Testprodukt'), false);
  const restored = parseBackup(text, catalog.products, id);
  assert.deepEqual(restored.decisions, state.decisions); assert.deepEqual(restored.history, []);
  assert.throws(() => parseBackup(text, catalog.products, id.replace(/1$/, '2')));
  assert.throws(() => parseBackup(text, catalog.products));
});

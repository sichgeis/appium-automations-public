const ID = /^catalog-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAGIC = new Uint8Array([72, 72, 67, 49]);
const encoder = new TextEncoder();
const aad = id => encoder.encode('household-catalog-v1:' + id);
export const catalogStorageKey = id => id === 'synthetic-demo-v1' ? 'household-swipe-synthetic-v1' : 'household-swipe:' + id;
export const catalogRecoveryKey = id => id === 'synthetic-demo-v1' ? 'household-swipe-before-import-v1' : 'household-before-import:' + id;

function validPeople(people) {
  return people && Object.keys(people).every(k => ['a', 'b', 'version'].includes(k))
    && Number.isSafeInteger(people.version) && people.version >= 1
    && ['a', 'b'].every(k => typeof people[k] === 'string' && people[k].trim() && people[k].length <= 24);
}

export function applyCatalogPeople(state, people) {
  if (people === undefined) return state;
  if (!validPeople(people)) throw new Error('Ungültige private Anzeigenamen.');
  if (state.peopleVersion === people.version) return state;
  return { ...state, names: { a: people.a, b: people.b }, peopleVersion: people.version };
}

export function validateCatalog(value) {
  const rootKeys = new Set(['format', 'version', 'id', 'synthetic', 'revision', 'products', 'coverage', 'ledgerTotals', 'people']);
  if (!value || value.format !== 'household-catalog' || value.version !== 1 || !ID.test(value.id)
    || Object.keys(value).some(k => !rootKeys.has(k)) || !Number.isSafeInteger(value.coverage?.receipts) || value.coverage.receipts < 0
    || value.synthetic !== false || !/^[a-f0-9]{64}$/.test(value.revision)
    || (value.people !== undefined && !validPeople(value.people))
    || !Array.isArray(value.products) || value.products.length > 10000) throw new Error('Ungültiger privater Katalog.');
  const ids = new Set(), purchases = new Set();
  const allowed = new Set(['id', 'name', 'brand', 'detail', 'merchant', 'count', 'quantity', 'total', 'low', 'high', 'priceLabel', 'variant', 'purchases']);
  for (const p of value.products) {
    if (!p || Object.keys(p).some(k => !allowed.has(k)) || !/^p-[a-f0-9]{24}$/.test(p.id) || ids.has(p.id)
      || !['name', 'brand', 'detail', 'merchant', 'quantity', 'priceLabel', 'variant'].every(k => typeof p[k] === 'string' && p[k].length <= 2000)
      || !p.name.trim() || !Number.isSafeInteger(p.total) || p.total < 0 || !Number.isInteger(p.count) || p.count < 1
      || ![p.low, p.high].every(n => n === null || (Number.isSafeInteger(n) && n >= 0))
      || (p.low === null) !== (p.high === null) || (p.low !== null && p.low > p.high)
      || !Array.isArray(p.purchases) || !p.purchases.length) throw new Error('Ungültige Produktkarte.');
    ids.add(p.id);
    for (const purchase of p.purchases) {
      if (!purchase || Object.keys(purchase).some(k => !['id', 'amount', 'month'].includes(k))
        || !/^p-[a-f0-9]{24}$/.test(purchase.id) || purchases.has(purchase.id)
        || !Number.isSafeInteger(purchase.amount) || purchase.amount < 0 || !/^\d{4}-\d{2}$/.test(purchase.month)) throw new Error('Ungültiger Kaufbezug.');
      purchases.add(purchase.id);
    }
    if (p.purchases.reduce((n, p) => n + p.amount, 0) !== p.total) throw new Error('Kaufsumme passt nicht zur Karte.');
  }
  if (!value.ledgerTotals || !Object.values(value.ledgerTotals).every(Number.isSafeInteger)
    || value.products.reduce((n, p) => n + p.total, 0) !== (value.ledgerTotals.food ?? 0) + (value.ledgerTotals.food_discount ?? 0)) throw new Error('Katalogsummen nicht nachvollziehbar.');
  return value;
}

export async function sealCatalog(catalog, cryptoApi = crypto, existingKey = null) {
  validateCatalog(catalog);
  const key = existingKey ? new Uint8Array(existingKey) : cryptoApi.getRandomValues(new Uint8Array(32));
  if (key.length !== 32) throw new Error('Ungültiger Katalogschlüssel.');
  const iv = cryptoApi.getRandomValues(new Uint8Array(12));
  const imported = await cryptoApi.subtle.importKey('raw', key, 'AES-GCM', false, ['encrypt']);
  const ciphertext = new Uint8Array(await cryptoApi.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad(catalog.id), tagLength: 128 }, imported, encoder.encode(JSON.stringify(catalog))));
  const bytes = new Uint8Array(16 + ciphertext.length); bytes.set(MAGIC); bytes.set(iv, 4); bytes.set(ciphertext, 16);
  return { bytes, key };
}

export async function openCatalog(bytes, key, id, cryptoApi = crypto) {
  if (!ID.test(id) || key.byteLength !== 32 || bytes.byteLength < 32 || bytes.byteLength > 4 * 1024 * 1024
    || !MAGIC.every((n, i) => bytes[i] === n)) throw new Error('Privater Katalog konnte nicht geöffnet werden.');
  try {
    const imported = await cryptoApi.subtle.importKey('raw', key, 'AES-GCM', false, ['decrypt']);
    const plain = await cryptoApi.subtle.decrypt({ name: 'AES-GCM', iv: bytes.slice(4, 16), additionalData: aad(id), tagLength: 128 }, imported, bytes.slice(16));
    const catalog = validateCatalog(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(plain)));
    if (catalog.id !== id) throw new Error();
    return catalog;
  } catch { throw new Error('Privater Katalog konnte nicht geöffnet werden. Bitte den ursprünglichen privaten Startlink verwenden.'); }
}

export function encodeKey(key) { return btoa(String.fromCharCode(...key)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', ''); }
function decodeKey(text) {
  if (!/^[a-zA-Z0-9_-]{43}$/.test(text ?? '')) throw new Error('Privaten Startlink erneut öffnen.');
  return Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/') + '='), c => c.charCodeAt(0));
}

export async function loadCatalog({ location, history, storage, demoProducts, fetcher = fetch, cryptoApi = crypto }) {
  const params = new URLSearchParams(location.hash.slice(1));
  const suppliedKey = params.get('key');
  const selected = params.get('catalog');
  // Remove the credential synchronously, before any network operation or rendering.
  if (suppliedKey !== null) history.replaceState(null, '', location.pathname + location.search + (ID.test(selected ?? '') ? '#catalog=' + selected : ''));
  const id = selected ?? storage.getItem('household-last-private-catalog');
  if (!id && suppliedKey === null) return { id: 'synthetic-demo-v1', synthetic: true, products: demoProducts };
  if (!ID.test(id ?? '')) throw new Error('Ungültiger privater Startlink.');
  const cacheKey = 'household-catalog-access:' + id;
  const encoded = suppliedKey ?? storage.getItem(cacheKey);
  const key = decodeKey(encoded);
  const response = await fetcher(new URL('./catalogs/' + id + '.bin', location.href), { credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-cache' });
  if (!response.ok) throw new Error('Privater Katalog noch nicht erreichbar. Bitte später erneut öffnen.');
  const catalog = await openCatalog(new Uint8Array(await response.arrayBuffer()), key, id, cryptoApi);
  storage.setItem(cacheKey, encoded);
  storage.setItem('household-last-private-catalog', id);
  return catalog;
}

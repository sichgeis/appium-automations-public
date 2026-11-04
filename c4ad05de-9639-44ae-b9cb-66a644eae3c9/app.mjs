import { products as demoProducts } from './products.mjs';
import { loadCatalog, catalogStorageKey, catalogRecoveryKey } from './catalog.mjs?v=catalog-3';
import { initialState, validateState, pending, assign, undo, summary, persist, swipeDirection, defaults } from './core.mjs';
import { MAX_BACKUP_BYTES, backupText, parseBackup, filename, shareFile, handOffShare, handOffTextShare, createBackup } from './backup.mjs?v=catalog-3';

const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(n / 100);
let catalog;
$('sort-view').hidden = true;
try {
  catalog = await loadCatalog({ location: window.location, history: window.history, storage: localStorage, demoProducts });
} catch (error) {
  $('error').textContent = error.message; $('error').hidden = false;
  document.querySelector('.backup-panel').hidden = true;
  throw new Error('Katalogstart angehalten.');
}
const products = catalog.products;
const STORAGE_KEY = catalogStorageKey(catalog.id);
const RECOVERY_KEY = catalogRecoveryKey(catalog.id);
$('sort-view').hidden = false;
if (!catalog.synthetic) {
  document.title = 'Tisch für zwei · Haushaltsverbrauch';
  document.querySelector('.demo-pill').textContent = 'Privater Katalog';
  document.querySelector('.card-foot span:last-child').textContent = 'Produktbild folgt';
  document.querySelector('#complete p').textContent = 'Alle Produkte sind zugeordnet. In der Übersicht kannst du jede Entscheidung ändern.';
  document.querySelector('footer span:last-child').textContent = 'KATALOG / 03';
  document.querySelector('.brand').href = '#catalog=' + catalog.id;
}

let state = initialState();
let storageBlocked = false;
let editing = null;
let activeView = 'sort';
let gesture = null;
let importCandidate = null;
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) state = validateState(JSON.parse(saved), products);
  if (!state.assessment) state = { ...state, assessment: initialState().assessment };
  if (!saved || !JSON.parse(saved).assessment) state = persist(localStorage, state, products, STORAGE_KEY);
} catch {
  storageBlocked = true;
  showError('Der lokale Demostand konnte nicht geladen werden. Er bleibt unverändert. Bitte einen anderen Browser verwenden oder den Browserspeicher prüfen.');
}

function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function save(next) {
  if (storageBlocked) return false;
  try { state = persist(localStorage, { ...next, savedAt: new Date().toISOString() }, products, STORAGE_KEY); $('error').hidden = true; return true; }
  catch { showError('Speichern fehlgeschlagen. Die Entscheidung wurde nicht übernommen. Bitte den Browserspeicher prüfen.'); return false; }
}
function label(choice) { return choice === 'shared' ? 'Gemeinsam' : `Hauptsächlich ${state.names[choice]}`; }
function announce(text) { $('announcement').textContent = text; }

function illustration(p) {
  if (!catalog.synthetic) return '<svg viewBox="0 0 200 180" xmlns="http://www.w3.org/2000/svg"><path d="M45 65h110l-10 90H55z" fill="#dce6d1"/><path d="M76 68V51a24 24 0 0148 0v17" fill="none" stroke="#6c8c61" stroke-width="8"/><path d="M80 100h40m-20-20v40" stroke="#719064" stroke-width="5"/></svg>';

  // Only trusted, synthetic fixture values enter this SVG; no imported HTML.
  const base = `<ellipse cx="100" cy="166" rx="65" ry="7" fill="#293a2412"/>`;
  let shape;
  if (p.kind === 'fruit') shape = `<path d="M103 55q-12-20 9-29" stroke="#65573a" stroke-width="6" fill="none"/><path d="M107 47q32-33 47-12-19 23-47 12" fill="#5f8453"/><path d="M102 64C47 31 29 96 56 135q19 32 44 13 25 18 45-12 29-48-2-72-21-15-41 0" fill="${p.accent}"/><path d="M65 77q-12 12-10 29" stroke="#f3aa87" stroke-width="8" stroke-linecap="round"/>`;
  else if (p.kind === 'cup') shape = `<path d="M43 56h114l-14 98H57z" fill="${p.accent}"/><path d="M48 83h104l-7 45H54z" fill="${p.color}"/><ellipse cx="100" cy="55" rx="59" ry="12" fill="#f6f4e7" stroke="${p.color}" stroke-width="4"/><text x="100" y="110" fill="white" text-anchor="middle" font-size="13" font-family="Georgia">${p.motif}</text>`;
  else if (p.kind === 'tray') shape = `<rect x="28" y="39" width="144" height="115" rx="15" fill="#e1dfcf" stroke="#cccabc" stroke-width="4"/><rect x="37" y="47" width="126" height="99" rx="9" fill="${p.accent}"/><path d="M46 70l95 48m-79-64 83 41m-97 8 64 34" stroke="#f3d9c6" stroke-width="10"/><rect x="26" y="81" width="148" height="43" fill="${p.color}"/><text x="100" y="106" fill="#fff8e6" text-anchor="middle" font-size="12" font-family="Georgia">${p.motif}</text>`;
  else shape = `<path d="M47 19h106l5 143H42z" fill="${p.color}"/><path d="M47 19h106v9H47zM42 153h116v9H42z" fill="#dbd3bd"/><rect x="51" y="36" width="98" height="97" rx="2" fill="${p.accent}"/><text x="100" y="57" text-anchor="middle" fill="#604331" font-size="7" letter-spacing="2">BEISPIELMARKE</text><text x="100" y="79" text-anchor="middle" fill="#604331" font-size="${p.motif.length > 7 ? 13 : 20}" font-family="Georgia">${p.motif}</text>${p.kind === 'chocolate' ? '<path d="M67 94h66v32H67z" fill="#69422c"/><path d="M89 94v32m22-32v32M67 110h66" stroke="#93603b" stroke-width="2"/><ellipse cx="133" cy="123" rx="9" ry="12" fill="#be8d50"/>' : '<path d="M65 99h70v27H65z" fill="#fff8df88"/><path d="M77 103v18m12-18v18m12-18v18m12-18v18m12-18v18" stroke="#ba9857" stroke-width="4"/>'}`;
  return `<svg viewBox="0 0 200 180" xmlns="http://www.w3.org/2000/svg">${base}${shape}</svg>`;
}

function render() {
  const ids = pending(state, products);
  const s = summary(state, products);
  const all = s.assigned + s.open;
  $('remaining-badge').textContent = ids.length;
  $('assigned-badge').textContent = s.count;
  $('progress-label').textContent = `${s.count} von ${products.length} Produkten zugeordnet`;
  $('coverage-label').textContent = `${all ? Math.round(s.assigned / all * 100) : 0} % des Warenwerts`;
  $('progress').max = products.length; $('progress').value = s.count;
  $('label-a').textContent = state.names.a; $('label-b').textContent = state.names.b;
  $('choose-b').setAttribute('aria-label', `Hauptsächlich ${state.names.b}`);
  $('choose-a').setAttribute('aria-label', `Hauptsächlich ${state.names.a}`);
  $('choose-shared').setAttribute('aria-label', 'Gemeinsam, 50/50');
  const done = ids.length === 0;
  $('deck').hidden = done; $('complete').hidden = !done;
  $('decision-controls').hidden = done; $('skip').hidden = done;
  $('undo').disabled = storageBlocked || !state.history.length;
  $('reviewer-tag').textContent = state.assessment.reviewer || 'Eigener Gerätestand';
  $('save-status').textContent = state.savedAt ? '✓ Auf diesem Gerät gespeichert · keine Synchronisierung' : (catalog.synthetic ? '◉ Nur auf diesem Browser gespeichert. Keine echten Bons.' : '◉ Bewertung bleibt auf diesem Gerät.');
  for (const id of ['export', 'share-backup', 'share-text', 'download-backup', 'import-backup', 'recovery-backup', 'confirm-import', 'import-text', 'preview-text']) $(id).disabled = storageBlocked;
  try { $('recovery-backup').hidden = !localStorage.getItem(RECOVERY_KEY); } catch { $('recovery-backup').hidden = true; }
  for (const id of ['choose-a', 'choose-b', 'choose-shared', 'skip']) $(id).disabled = storageBlocked;
  if (!done) {
    const p = products.find(p => p.id === ids[0]);
    $('merchant').textContent = p.merchant;
    $('variant').textContent = p.variant ?? 'Wiederholungskäufe';
    $('scene').innerHTML = illustration(p);
    $('product-brand').textContent = p.brand;
    $('product-title').textContent = p.name; $('product-detail').textContent = p.detail;
    $('purchase-count').textContent = `${p.count} Bons`; $('total').textContent = money(p.total);
    $('price-label').textContent = p.priceLabel ?? (p.weight ? 'Preis / kg' : 'Preis / Packung');
    $('price').textContent = p.low === null ? 'unbekannt' : p.low === p.high ? money(p.low) : `${money(p.low)}–${money(p.high)}`;
    $('quantity').textContent = p.quantity;
    $('product-card').setAttribute('aria-label', `${p.name}. ${p.detail}. Nach links, oben oder rechts wischen.`);
  }
  if (activeView === 'overview') renderOverview(s);
}

function element(tag, text, cls) {
  const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e;
}
function renderOverview(s) {
  $('totals').replaceChildren(...['a', 'b'].map(k => {
    const tile = element('div', undefined, 'total-tile'); tile.append(element('span', state.names[k]), element('strong', money(s[k]))); return tile;
  }));
  $('open-cost').textContent = `${money(s.open)} noch offen · ${s.count} von ${products.length} Produkten zugeordnet. ${catalog.synthetic ? 'Alle Beträge sind erfunden.' : 'Kaufbezogene Warenkosten nach direkt zugeordneten Produktrabatten; Pfand, andere Waren und offene Rabatte separat.'}`;
  if (!catalog.synthetic) {
    const labels = { deposit: 'Pfand', other: 'Andere Waren', refund: 'Rückgaben', discount: 'Weitere Rabatte' };
    $('ledger-summary').hidden = false;
    $('ledger-summary').replaceChildren(element('p', `${catalog.coverage.receipts} erfasste Bons. Außerhalb der zugeordneten Lebensmittelkosten:`),
      ...Object.entries(labels).filter(([key]) => catalog.ledgerTotals[key]).map(([key, name]) => element('p', `${name}: ${money(catalog.ledgerTotals[key])}`)));
  }
  $('product-list').replaceChildren(...products.map(p => {
    const d = state.decisions[p.id];
    const row = element('button', undefined, 'product-row'); row.type = 'button';
    const copy = element('span', undefined, 'row-copy');
    copy.append(element('strong', p.name), element('small', p.detail));
    copy.append(element('small', d ? `${label(d.choice)} · ${d.shareA}/${100 - d.shareA}` : 'Noch offen'));
    row.append(element('span', p.kind === 'fruit' ? '◉' : '▥', 'mini-product'), copy, element('span', money(p.total), 'row-cost'));
    row.addEventListener('click', () => openEdit(p));
    row.disabled = storageBlocked;
    return row;
  }));
}
function changeView(view) {
  cancelGesture(); activeView = view;
  if (view === 'overview') renderOverview(summary(state, products));
  $('sort-view').hidden = view !== 'sort'; $('overview-view').hidden = view !== 'overview';
  for (const v of ['sort', 'overview']) { $(`${v}-tab`).classList.toggle('active', v === view); $(`${v}-tab`).setAttribute('aria-selected', String(v === view)); }
}
function decide(choice) {
  if (activeView !== 'sort' || storageBlocked) return;
  const id = pending(state, products)[0]; if (!id) return;
  if (save(assign(state, id, choice))) {
    announce(`${products.find(p => p.id === id).name}: ${label(choice)}. Gespeichert.`); render();
  }
}
function openEdit(p) {
  editing = p.id;
  const d = state.decisions[p.id];
  $('edit-title').textContent = p.name;
  $('option-a').textContent = label('a'); $('option-b').textContent = label('b');
  $('edit-choice').value = d?.choice ?? 'open'; $('share').value = d?.shareA ?? 50;
  $('share-name').textContent = state.names.a;
  updateShare(); $('edit').showModal();
}
function updateShare() {
  const open = $('edit-choice').value === 'open';
  $('share-control').hidden = open;
  const share = Number($('share').value);
  $('share-value').textContent = `${share} %`;
  $('share-description').textContent = open ? 'Diese Karte wird wieder zur Zuordnung angeboten.' : `${state.names.a}: ${share} % · ${state.names.b}: ${100 - share} %. Eine Kostenannahme, kein gemessener Verbrauch.`;
}

$('sort-tab').onclick = () => changeView('sort');
$('overview-tab').onclick = $('complete-overview').onclick = () => changeView('overview');
for (const [id, choice] of [['choose-a', 'a'], ['choose-b', 'b'], ['choose-shared', 'shared']]) $(id).onclick = () => decide(choice);
$('undo').onclick = () => { if (save(undo(state))) { render(); announce('Letzte Zuordnung zurückgenommen.'); } };
$('skip').onclick = () => {
  const ids = pending(state, products); if (ids.length < 2) { announce('Dies ist das letzte offene Produkt. Du kannst es offen lassen.'); return; }
  const next = structuredClone(state); next.queue = [...ids.slice(1), ids[0]];
  if (save(next)) { render(); announce('Produkt zurückgestellt.'); }
};
$('settings-open').onclick = () => { $('name-a').value = state.names.a; $('name-b').value = state.names.b; $('reviewer').value = state.assessment.reviewer; $('settings').showModal(); };
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $(b.dataset.close).close());
$('settings-form').onsubmit = e => {
  e.preventDefault(); const next = structuredClone(state); next.names = { a: $('name-a').value.trim(), b: $('name-b').value.trim() };
  next.assessment.reviewer = $('reviewer').value.trim();
  if (!next.names.a || !next.names.b) return;
  if (save(next)) { $('settings').close(); render(); announce('Namen lokal gespeichert.'); }
};
$('share').oninput = updateShare;
$('edit-choice').onchange = () => { $('share').value = defaults[$('edit-choice').value] ?? 50; updateShare(); };
$('edit-form').onsubmit = e => {
  e.preventDefault(); if (save(assign(state, editing, $('edit-choice').value, Number($('share').value)))) { $('edit').close(); render(); announce('Zuordnung geändert und gespeichert.'); }
};
function backupStatus(text) { $('backup-status').textContent = text; }
function downloadBackup() {
  if (storageBlocked) return;
  const blob = new Blob([backupText(state, products, catalog.id)], { type: 'application/json' });
  const url = URL.createObjectURL(blob); const a = element('a');
  a.href = url; a.download = filename(state); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  backupStatus('Exportdatei erstellt. Du kannst sie als Anhang per Mail oder Messenger verschicken. Ein Empfang wurde noch nicht bestätigt.');
}
$('export').onclick = $('download-backup').onclick = downloadBackup;
$('share-backup').onclick = async () => {
  if (storageBlocked) return;
  // No awaits before share(): preserve the user gesture required by mobile browsers.
  const file = shareFile(navigator, backupText(state, products, catalog.id), state);
  if (!file) {
    downloadBackup();
    backupStatus('Dieser Browser unterstützt das Dateiteilen nicht. Download gestartet: bitte die Datei direkt in Signal oder Mail anhängen. Alternativ „Als Nachricht teilen“ verwenden.');
    return;
  }
  $('share-backup').disabled = true;
  try {
    const result = await handOffShare(navigator, file);
    backupStatus(result === 'cancelled' ? 'Teilen abgebrochen. Deine Bewertung bleibt gespeichert.' : 'Datei an das Teilen-Menü übergeben. Falls Signal keinen Anhang zeigt, „Als Nachricht teilen“ verwenden. Versand bitte in Signal prüfen.');
  } catch (error) { backupStatus(error.message); }
  finally { $('share-backup').disabled = storageBlocked; }
};
$('share-text').onclick = async () => {
  if (storageBlocked) return;
  $('share-text').disabled = true;
  try {
    const result = await handOffTextShare(navigator, JSON.stringify(createBackup(state, products, new Date(), catalog.id)));
    backupStatus(result === 'cancelled' ? 'Teilen abgebrochen. Deine Bewertung bleibt gespeichert.' : 'Bewertung als Nachricht übergeben. Bitte prüfen, dass Signal den vollständigen Text zeigt. Empfangene Nachrichten lassen sich über „Text wiederherstellen“ importieren.');
  } catch (error) { backupStatus(error.message); }
  finally { $('share-text').disabled = storageBlocked; }
};
function previewImport(restored) {
  importCandidate = restored;
  const sum = summary(restored, products);
  $('import-summary').textContent = `${restored.assessment.reviewer || 'Bewertung ohne Namen'} · ${sum.count} von ${products.length} Produkten zugeordnet · ${restored.assessment.id === state.assessment.id ? 'dieselbe Bewertung' : 'andere unabhängige Bewertung'}.${catalog.synthetic ? '' : ' Kompakter Export: frühere Rückgängig-Schritte sind nicht enthalten.'}`;
  $('import-preview').showModal();
}
$('import-backup').onclick = () => { $('backup-file').value = ''; $('backup-file').click(); };
$('import-text').onclick = () => { $('backup-text').value = ''; $('text-import-error').textContent = ''; $('text-import').showModal(); };
$('preview-text').onclick = () => {
  try {
    const restored = parseBackup($('backup-text').value.trim(), products, catalog.id);
    $('text-import').close(); previewImport(restored);
  } catch (error) { $('text-import-error').textContent = error.message; }
};
$('backup-file').onchange = async () => {
  const file = $('backup-file').files[0]; if (!file || storageBlocked) return;
  try {
    if (file.size > MAX_BACKUP_BYTES) throw new Error('Die Datei ist zu groß (maximal 2 MB).');
    previewImport(parseBackup(await file.text(), products, catalog.id));
  } catch (error) { backupStatus(error.message); }
};
$('recovery-backup').onclick = () => {
  try { previewImport(parseBackup(localStorage.getItem(RECOVERY_KEY), products, catalog.id)); }
  catch (error) { backupStatus(error.message); }
};
$('confirm-import').onclick = () => {
  if (!importCandidate || storageBlocked) return;
  try {
    // Save the old assessment first. On failure the active state remains unchanged.
    localStorage.setItem(RECOVERY_KEY, backupText(state, products, catalog.id));
    if (save(importCandidate)) {
      importCandidate = null; $('import-preview').close(); render();
      backupStatus('Bewertung wiederhergestellt. Den Stand vor diesem Import kannst du hier ebenfalls wiederherstellen.');
    }
  } catch { backupStatus('Die vorherige Bewertung konnte nicht gesichert werden. Kein Import vorgenommen.'); }
};
document.addEventListener('keydown', e => {
  if (e.altKey || e.ctrlKey || e.metaKey || document.querySelector('dialog[open]') || /INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName) || activeView !== 'sort') return;
  const choice = { ArrowLeft: 'b', ArrowRight: 'a', ArrowUp: 'shared' }[e.key];
  if (choice) { e.preventDefault(); decide(choice); }
});

const card = $('product-card');
function cancelGesture() {
  gesture = null; card.style.transform = ''; $('swipe-stamp').style.opacity = '0';
}
card.addEventListener('pointerdown', e => {
  if (!e.isPrimary || e.button !== 0 || gesture || storageBlocked) return;
  gesture = { id: e.pointerId, x: e.clientX, y: e.clientY };
  card.setPointerCapture(e.pointerId);
});
card.addEventListener('pointermove', e => {
  if (!gesture || e.pointerId !== gesture.id) return;
  const dx = e.clientX - gesture.x; const dy = e.clientY - gesture.y;
  card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 22}deg)`;
  const direction = swipeDirection(dx, dy, card.clientWidth);
  $('swipe-stamp').textContent = direction ? label(direction) : '';
  $('swipe-stamp').style.opacity = direction ? '.96' : '0';
});
card.addEventListener('pointerup', e => {
  if (!gesture || e.pointerId !== gesture.id) return;
  const direction = swipeDirection(e.clientX - gesture.x, e.clientY - gesture.y, card.clientWidth);
  cancelGesture(); if (direction) decide(direction);
});
card.addEventListener('pointercancel', cancelGesture);
card.addEventListener('lostpointercapture', cancelGesture);
window.addEventListener('blur', cancelGesture);
// Prevent stale tabs from silently overwriting decisions made in another tab.
window.addEventListener('storage', e => {
  if (e.key !== STORAGE_KEY) return;
  storageBlocked = true; cancelGesture(); render();
  showError('Der Demostand wurde in einem anderen Tab geändert. Bitte diese Seite neu laden, bevor du weitermachst.');
});
render();

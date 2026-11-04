import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, assign, pending } from '../web/core.mjs';
import { products } from '../web/products.mjs';
import { createBackup, backupText, parseBackup, shareFile, handOffShare, MAX_BACKUP_BYTES } from '../web/backup.mjs';

test('backup restores independent assessment, names, shares, queue and undo history exactly', () => {
  const state = assign(initialState(), products[0].id, 'shared', 72);
  state.assessment.reviewer = 'Testperson'; state.queue = [products[2].id];
  assert.deepEqual(parseBackup(backupText(state, products), products), state);
  assert.equal(pending(parseBackup(backupText(state, products), products), products)[0], products[2].id);
  assert.notEqual(initialState().assessment.id, state.assessment.id);
});
test('mismatched product catalog and future schema cannot replace a saved assessment', () => {
  for (const mutate of [b => { b.dataset = 'other'; }, b => { b.version = 5; }, b => { b.products.pop(); }, b => { b.products[0].total++; }, b => { b.products[1] = b.products[0]; }, b => { delete b.state.assessment; }, b => { b.state.decisions.fake = { choice: 'a', shareA: 100 }; }]) {
    const backup = createBackup(initialState(), products); mutate(backup);
    assert.throws(() => parseBackup(JSON.stringify(backup), products));
  }
});
test('bad JSON, oversized input and invalid saved history are rejected', () => {
  assert.throws(() => parseBackup('{oops', products), /JSON/);
  assert.throws(() => parseBackup('x'.repeat(MAX_BACKUP_BYTES + 1), products), /groß/);
  const backup = createBackup(initialState(), products); backup.state.history.push({ id: products[0].id, before: { choice: 'shared', shareA: 101 } });
  assert.throws(() => parseBackup(JSON.stringify(backup), products));
});
test('previous demo exports can be restored with a new assessment identity', () => {
  const legacy = { ...assign(initialState(), products[1].id, 'b'), dataset: 'synthetic-demo-v1' };
  delete legacy.assessment;
  const restored = parseBackup(JSON.stringify(legacy), products);
  assert.ok(restored.assessment.id);
  assert.deepEqual(restored.decisions, legacy.decisions);
});
test('share attaches the full restorable file, not only a page link', async () => {
  const state = assign(initialState(), products[2].id, 'shared');
  let attachment;
  const api = { canShare: ({ files }) => files[0].type === 'application/json', share: async data => { attachment = data; } };
  const file = shareFile(api, backupText(state, products), state);
  assert.equal(await handOffShare(api, file), 'handed-off');
  assert.equal(attachment.url, undefined);
  assert.deepEqual(parseBackup(await attachment.files[0].text(), products), state);
});
test('unsupported JSON share falls back to text file with identical restorable bytes', async () => {
  const state = initialState(); const text = backupText(state, products);
  const api = { share() {}, canShare: ({ files }) => files[0].type === 'text/plain' };
  const file = shareFile(api, text, state);
  assert.equal(file.type, 'text/plain'); assert.match(file.name, /\.txt$/);
  assert.equal(await file.text(), text);
  assert.deepEqual(parseBackup(await file.text(), products), state);
});
test('unsupported file sharing returns download fallback without sending anything', () => {
  assert.equal(shareFile({}, '{}', initialState()), null);
  assert.equal(shareFile({ share() { assert.fail('must not send'); }, canShare() { return false; } }, '{}', initialState()), null);
});
test('share cancellation stays cancellation, failures do not claim successful delivery', async () => {
  assert.equal(await handOffShare({ share() { throw Object.assign(new Error(), { name: 'AbortError' }); } }, new File(['{}'], 'demo.json')), 'cancelled');
  await assert.rejects(handOffShare({ share() { throw new Error('failed'); } }, new File(['{}'], 'demo.json')), /herunterladen/);
});

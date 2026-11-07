import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, assign, undo, pending, regroupState, validateState } from '../web/core.mjs';
import { backupText, parseBackup } from '../web/backup.mjs';

const old = ['brand-a', 'brand-b', 'sort-a', 'sort-b', 'unchanged'].map(id => ({ id, total: 100 }));
const products = ['merged', 'sort', 'unchanged'].map(id => ({ id, total: 100 }));
const regrouping = { version: 1, sources: old.map(({ id }, i) => ({ id, target: ['merged', 'merged', 'sort', 'sort', 'unchanged'][i] })) };
const decide = entries => entries.reduce((state, [id, choice, share]) => assign(state, id, choice, share), initialState());
const migrate = state => regroupState(state, products, regrouping);

test('complete agreement preserves choices, custom shares and assessment metadata without mutating the source', () => {
  const state = decide([['brand-a', 'shared', 67], ['brand-b', 'shared', 67], ['unchanged', 'b', 12]]);
  state.savedAt = '2026-11-07T10:00:00Z'; state.assessment.reviewer = 'Synthetic'; state.names.a = 'Test';
  const before = structuredClone(state);
  const next = migrate(state);
  assert.deepEqual(next.decisions, { merged: { choice: 'shared', shareA: 67 }, unchanged: { choice: 'b', shareA: 12 } });
  for (const key of ['names', 'assessment', 'savedAt']) assert.deepEqual(next[key], state[key]);
  assert.equal(next.groupingVersion, 1); assert.deepEqual(next.groupingConflicts, []);
  assert.deepEqual(state, before);
});

test('disagreement in choice or share remains open; partial agreement never becomes a majority decision', () => {
  for (const second of [['brand-b', 'a', 50], ['brand-b', 'shared', 51]]) {
    const next = migrate(decide([['brand-a', 'shared', 50], second]));
    assert.equal(next.decisions.merged, undefined); assert.deepEqual(next.groupingConflicts, ['merged']);
  }
  const partial = migrate(decide([['brand-a', 'shared', 50]]));
  assert.deepEqual(partial.decisions, {}); assert.deepEqual(partial.groupingConflicts, []);
  const extraOld = [...old, { id: 'brand-c' }];
  const map = { version: 1, sources: [...regrouping.sources, { id: 'brand-c', target: 'merged' }] };
  const majority = decide([['brand-a', 'a'], ['brand-b', 'a']]);
  validateState(majority, extraOld);
  assert.equal(regroupState(majority, products, map).decisions.merged, undefined);
  const partialConflict = regroupState(decide([['brand-a', 'a'], ['brand-b', 'b']]), products, map);
  assert.deepEqual(partialConflict.groupingConflicts, ['merged']);
});

test('queue remaps and deduplicates targets, with open conflicts first; only unchanged undo survives', () => {
  const state = decide([['unchanged', 'a'], ['brand-a', 'a'], ['brand-b', 'b'], ['sort-a', 'shared']]);
  state.queue = ['sort-a', 'brand-b', 'sort-b', 'brand-a', 'unchanged'];
  const next = migrate(state);
  assert.deepEqual(next.queue, ['merged', 'sort', 'unchanged']);
  assert.deepEqual(pending(next, products), ['merged', 'sort']);
  assert.deepEqual(next.history, [{ id: 'unchanged', before: null }]);
  assert.equal(undo(next).decisions.unchanged, undefined);
  assert.deepEqual(migrate(next), next);
  const resolved = assign(next, 'merged', 'b');
  assert.deepEqual(migrate(resolved), resolved);
});

test('migration rejects foreign IDs in every old collection, invalid mappings and future versions', () => {
  for (const change of [s => { s.decisions.foreign = { choice: 'a', shareA: 100 }; }, s => { s.queue.push('foreign'); }, s => { s.history.push({ id: 'foreign', before: null }); }]) {
    const state = initialState(); change(state); assert.throws(() => migrate(state));
  }
  for (const change of [r => { r.version = 2; }, r => { r.extra = true; }, r => { r.sources[0].extra = true; }, r => { r.sources.push(r.sources[0]); }, r => { r.sources[0].target = 'foreign'; }, r => { r.sources = r.sources.filter(s => s.id !== 'unchanged'); }, r => { r.sources[0].id = 'merged'; }, r => { r.sources[0].target = 'unchanged'; }]) {
    const map = structuredClone(regrouping); change(map);
    assert.throws(() => regroupState(initialState(), products, map));
  }
  const state = migrate(initialState()); state.groupingVersion = 2;
  assert.throws(() => migrate(state));
  assert.throws(() => regroupState(state, products, null));
  assert.throws(() => migrate({ ...migrate(initialState()), queue: ['brand-a'] }));
});

test('state validation checks grouping metadata shape, duplicates and current IDs', () => {
  for (const change of [s => { s.groupingVersion = 0; }, s => { s.groupingVersion = 1.5; }, s => { s.groupingVersion = '1'; }, s => { s.groupingConflicts = ['foreign']; }, s => { s.groupingConflicts = ['merged', 'merged']; }, s => { s.groupingConflicts = {}; }, s => { delete s.groupingVersion; }]) {
    const state = migrate(initialState()); change(state); assert.throws(() => validateState(state, products));
  }
});

test('legacy compact backup migrates and current compact round trip preserves grouping metadata', () => {
  const oldState = decide([['brand-a', 'a'], ['brand-b', 'b'], ['sort-a', 'shared', 63], ['sort-b', 'shared', 63], ['unchanged', 'b']]);
  oldState.queue = ['brand-a', 'sort-b'];
  const legacy = backupText(oldState, old, 'private-test');
  assert.equal(JSON.parse(legacy).groupingVersion, undefined);
  const restored = parseBackup(legacy, products, 'private-test', regrouping);
  assert.deepEqual(restored.decisions, { sort: { choice: 'shared', shareA: 63 }, unchanged: { choice: 'b', shareA: 0 } });
  assert.deepEqual(restored.groupingConflicts, ['merged']);
  const currentText = backupText(restored, products, 'private-test');
  assert.equal(JSON.parse(currentText).groupingVersion, 1);
  assert.deepEqual(parseBackup(currentText, products, 'private-test', regrouping), { ...restored, queue: ['merged'] });
  assert.throws(() => parseBackup(currentText, products, 'private-test'));
  assert.throws(() => parseBackup(legacy, products, 'other', regrouping));
  for (const change of [b => { b.groupingVersion = 2; }, b => { b.decisions.foreign = ['a', 100]; }, b => { b.queue.push('foreign'); }, b => { b.groupingConflicts.push('foreign'); }]) {
    const backup = JSON.parse(currentText); change(backup);
    assert.throws(() => parseBackup(JSON.stringify(backup), products, 'private-test', regrouping));
  }
  const unknownLegacy = JSON.parse(legacy); unknownLegacy.decisions.foreign = ['a', 100];
  assert.throws(() => parseBackup(JSON.stringify(unknownLegacy), products, 'private-test', regrouping));
});

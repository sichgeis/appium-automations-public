import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, assign, undo, pending, summary, persist, validateState, swipeDirection } from '../web/core.mjs';
import { products } from '../web/products.mjs';

test('sorts, sizes and unknown identity keep independent decisions', () => {
  const state = assign(initialState(), 'choc-hazelnut-100', 'a');
  assert.equal(state.decisions['choc-hazelnut-100'].shareA, 100);
  for (const id of ['choc-strawberry-100', 'choc-hazelnut-200', 'unknown-chocolate']) assert.ok(pending(state, products).includes(id));
  assert.equal(new Set(products.map(p => p.id)).size, products.length);
});
test('three directions have agreed initial cost assumptions', () => {
  for (const [choice, share] of [['a', 100], ['b', 0], ['shared', 50]]) {
    assert.equal(assign(initialState(), products[0].id, choice).decisions[products[0].id].shareA, share);
  }
});
test('undo restores changed proportions and reopens newly assigned product', () => {
  const id = products[0].id;
  const first = assign(initialState(), id, 'shared', 63);
  const edited = assign(first, id, 'b');
  assert.deepEqual(undo(edited).decisions[id], first.decisions[id]);
  const cleared = undo(undo(edited));
  assert.equal(cleared.decisions[id], undefined);
  assert.equal(pending(cleared, products)[0], id);
  assert.equal(first.decisions[id].shareA, 63);
});
test('completed deck stays complete after reload; reopening preserves other assignments', () => {
  let state = initialState();
  for (const p of products) state = assign(state, p.id, 'shared');
  state = validateState(JSON.parse(JSON.stringify(state)), products);
  assert.deepEqual(pending(state, products), []);
  state = assign(state, products[2].id, 'open');
  assert.deepEqual(pending(state, products), [products[2].id]);
  assert.equal(Object.keys(state.decisions).length, products.length - 1);
});
test('shared odd-cent amounts leave no missing cents and open cost remains visible', () => {
  const fixture = [{ id: 'odd', total: 179 }, { id: 'open', total: 299 }];
  const sum = summary(assign(initialState(), 'odd', 'shared'), fixture);
  assert.deepEqual(sum, { a: 90, b: 89, open: 299, assigned: 179, count: 1 });
});
test('storage failure leaves previous state intact', () => {
  const previous = initialState(); const next = assign(previous, products[0].id, 'a');
  assert.throws(() => persist({ setItem() { throw new Error('quota'); } }, next, products), /quota/);
  assert.deepEqual(previous.decisions, {});
});
test('durable state round trip retains names, queue and custom proportions', () => {
  const state = assign(initialState(), products[1].id, 'shared', 71);
  state.queue = [products[2].id, products[0].id];
  let payload;
  persist({ setItem(key, value) { payload = value; } }, state, products);
  assert.deepEqual(validateState(JSON.parse(payload), products), state);
});
test('reject malformed, unknown and future-version saved data', () => {
  for (const modify of [s => { s.version = 9; }, s => { s.decisions.unknown = { choice: 'a', shareA: 100 }; }, s => { s.names.a = ''; }, s => { s.history = [{}]; }, s => { s.queue = [products[0].id, products[0].id]; }]) {
    const state = initialState(); modify(state);
    assert.throws(() => validateState(state, products));
  }
  for (const value of [-1, 101, NaN, 2.5]) assert.throws(() => assign(initialState(), products[0].id, 'shared', value));
});
test('short, diagonal and downward gestures do not assign; all intended directions work', () => {
  for (const [x, y] of [[40, 0], [0, -40], [200, 190], [0, 180]]) assert.equal(swipeDirection(x, y, 350), null);
  assert.equal(swipeDirection(140, 20, 350), 'a');
  assert.equal(swipeDirection(-140, 20, 350), 'b');
  assert.equal(swipeDirection(10, -140, 350), 'shared');
});

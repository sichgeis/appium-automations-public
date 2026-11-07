export const STORAGE_KEY = 'household-swipe-synthetic-v1';
export const defaults = { a: 100, b: 0, shared: 50 };
export const initialState = () => ({ version: 1, decisions: {}, queue: [], history: [], names: { a: 'Person A', b: 'Person B' }, assessment: { id: crypto.randomUUID(), reviewer: '' } });

export function validateState(value, products) {
  const ids = new Set(products.map(p => p.id));
  const decision = d => d && Object.hasOwn(defaults, d.choice) && Number.isInteger(d.shareA) && d.shareA >= 0 && d.shareA <= 100;
  if (!value || value.version !== 1 || !value.decisions || typeof value.decisions !== 'object' || Array.isArray(value.decisions)
    || !Object.entries(value.decisions).every(([id, d]) => ids.has(id) && decision(d))
    || !Array.isArray(value.queue) || !value.queue.every(id => ids.has(id)) || new Set(value.queue).size !== value.queue.length
    || !value.names || !['a', 'b'].every(k => typeof value.names[k] === 'string' && value.names[k].trim() && value.names[k].length <= 24)
    || (value.assessment !== undefined && (!value.assessment || !/^[a-f0-9-]{36}$/i.test(value.assessment.id) || typeof value.assessment.reviewer !== 'string' || value.assessment.reviewer.length > 64))
    || (value.groupingVersion !== undefined && (!Number.isInteger(value.groupingVersion) || value.groupingVersion < 1))
    || (value.groupingConflicts !== undefined && (!Array.isArray(value.groupingConflicts) || !value.groupingConflicts.every(id => ids.has(id)) || new Set(value.groupingConflicts).size !== value.groupingConflicts.length || value.groupingVersion === undefined))
    || !Array.isArray(value.history) || !value.history.every(h => h && ids.has(h.id) && (h.before === null || decision(h.before)))) {
    throw new Error('Gespeicherter Demostand ist ungültig. Er wurde nicht überschrieben.');
  }
  return value;
}

// Shared by catalog validation and migration; no assessment data is needed here.
export function validateRegrouping(regrouping, products) {
  if (regrouping === undefined || regrouping === null) return null;
  const fail = () => { throw new Error('Die Gruppierung passt nicht zu diesem Katalog.'); };
  const current = new Set(products.map(p => p.id));
  if (typeof regrouping !== 'object' || Array.isArray(regrouping)
    || !Object.keys(regrouping).every(key => ['version', 'sources'].includes(key))
    || current.size !== products.length || regrouping.version !== 1 || !Array.isArray(regrouping.sources) || !regrouping.sources.length) fail();
  const sources = new Map();
  const groups = new Map();
  for (const source of regrouping.sources) {
    if (!source || typeof source !== 'object' || Array.isArray(source)
      || !Object.keys(source).every(key => ['id', 'target'].includes(key))
      || typeof source.id !== 'string' || !source.id || typeof source.target !== 'string'
      || !current.has(source.target) || sources.has(source.id) || (current.has(source.id) && source.id !== source.target)) fail();
    sources.set(source.id, source.target);
    if (!groups.has(source.target)) groups.set(source.target, []);
    groups.get(source.target).push(source.id);
  }
  if (groups.size !== current.size) fail();
  for (const [target, ids] of groups) if (ids.includes(target) && ids.length !== 1) fail();
  return { sources, groups };
}

// Validate against the complete source catalog before replacing any product IDs.
export function regroupState(state, products, regrouping) {
  const mapping = validateRegrouping(regrouping, products);
  if (!mapping) {
    if (state?.groupingVersion !== undefined) throw new Error('Die Gruppierung passt nicht zu diesem Katalog.');
    return validateState(state, products);
  }
  const { sources, groups } = mapping;
  const fail = () => { throw new Error('Die Gruppierung passt nicht zu diesem Katalog.'); };
  if (state?.groupingVersion !== undefined) {
    if (state.groupingVersion !== regrouping.version) fail();
    return validateState(state, products);
  }
  validateState(state, [...sources.keys()].map(id => ({ id })));
  const next = structuredClone(state);
  next.decisions = {};
  next.groupingVersion = regrouping.version;
  next.groupingConflicts = [];
  for (const [target, ids] of groups) {
    const decisions = ids.filter(id => Object.hasOwn(state.decisions, id)).map(id => state.decisions[id]);
    const distinct = new Set(decisions.map(d => `${d.choice}:${d.shareA}`));
    if (distinct.size > 1) next.groupingConflicts.push(target);
    if (decisions.length === ids.length && distinct.size === 1) {
      Object.defineProperty(next.decisions, target, { value: structuredClone(decisions[0]), enumerable: true, configurable: true, writable: true });
    }
  }
  // Old group undo entries no longer describe one current decision.
  next.history = next.history.filter(h => sources.get(h.id) === h.id);
  const queue = [...new Set(state.queue.map(id => sources.get(id)))];
  const conflicts = next.groupingConflicts.filter(id => !next.decisions[id]);
  next.queue = [...conflicts, ...queue.filter(id => !conflicts.includes(id))];
  return validateState(next, products);
}

export function pending(state, products) {
  return [...state.queue, ...products.map(p => p.id).filter(id => !state.queue.includes(id))].filter(id => !state.decisions[id]);
}

export function assign(state, id, choice, shareA = defaults[choice]) {
  if (choice !== 'open' && (!Object.hasOwn(defaults, choice) || !Number.isInteger(shareA) || shareA < 0 || shareA > 100)) throw new Error('Ungültiger Kostenanteil.');
  const next = structuredClone(state);
  next.history.push({ id, before: next.decisions[id] ?? null });
  if (choice === 'open') delete next.decisions[id];
  else next.decisions[id] = { choice, shareA };
  return next;
}

export function undo(state) {
  const next = structuredClone(state);
  const previous = next.history.pop();
  if (!previous) return next;
  if (previous.before === null) delete next.decisions[previous.id];
  else next.decisions[previous.id] = previous.before;
  next.queue = [previous.id, ...next.queue.filter(id => id !== previous.id)];
  return next;
}

export function summary(state, products) {
  return products.reduce((sum, p) => {
    const d = state.decisions[p.id];
    if (!d) { sum.open += p.total; return sum; }
    const a = (p.purchases ?? [{ amount: p.total }]).reduce((n, purchase) => n + Math.round(purchase.amount * d.shareA / 100), 0);
    sum.a += a; sum.b += p.total - a; sum.assigned += p.total; sum.count++;
    return sum;
  }, { a: 0, b: 0, open: 0, assigned: 0, count: 0 });
}

// Only commit the in-memory state after a successful durable write.
export function persist(storage, next, products, key = STORAGE_KEY) {
  validateState(next, products);
  storage.setItem(key, JSON.stringify(next));
  return next;
}

export function swipeDirection(dx, dy, width) {
  const threshold = Math.max(65, Math.min(110, width * 0.23));
  if (Math.abs(dx) >= threshold && Math.abs(dx) > Math.abs(dy) * 1.25) return dx > 0 ? 'a' : 'b';
  if (dy <= -threshold && Math.abs(dy) > Math.abs(dx) * 1.25) return 'shared';
  return null;
}

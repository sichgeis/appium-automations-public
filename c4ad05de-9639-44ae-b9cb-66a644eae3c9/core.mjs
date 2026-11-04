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
    || !Array.isArray(value.history) || !value.history.every(h => h && ids.has(h.id) && (h.before === null || decision(h.before)))) {
    throw new Error('Gespeicherter Demostand ist ungültig. Er wurde nicht überschrieben.');
  }
  return value;
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
    const a = Math.round(p.total * d.shareA / 100);
    sum.a += a; sum.b += p.total - a; sum.assigned += p.total; sum.count++;
    return sum;
  }, { a: 0, b: 0, open: 0, assigned: 0, count: 0 });
}

// Only commit the in-memory state after a successful durable write.
export function persist(storage, next, products) {
  validateState(next, products);
  storage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function swipeDirection(dx, dy, width) {
  const threshold = Math.max(65, Math.min(110, width * 0.23));
  if (Math.abs(dx) >= threshold && Math.abs(dx) > Math.abs(dy) * 1.25) return dx > 0 ? 'a' : 'b';
  if (dy <= -threshold && Math.abs(dy) > Math.abs(dx) * 1.25) return 'shared';
  return null;
}

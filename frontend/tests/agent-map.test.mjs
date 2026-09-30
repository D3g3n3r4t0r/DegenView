import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
// Load production ES module without changing the repository package type.
const source = await readFile(new URL('../static/onchain/agent-map-model.js', import.meta.url), 'utf8');
const { projectGraph, projectsIn, normalizeEvents } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const row = (token, extra = {}) => ({ t: 100, chain: 'solana', token, kind: 'study', text: 'Observed', ...extra });
const node = (g, id) => g.nodes.find(n => n.id === id);
test('same ticker and different case-sensitive identities remain separate', () => {
  const items = [row('AbC', { symbol: 'X' }), row('abc', { symbol: 'X' })];
  const projects = projectsIn(items); assert.equal(projects.length, 2);
  const graph = projectGraph({ items, key: projects[0].key, receivedAt: 1000, now: 1001 });
  assert.equal(graph.eventCount, 1); assert.equal(graph.usage, null);
});
test('same timestamp events are preserved; unknown kinds remain visible', () => {
  const g = projectGraph({ items: [row('A'), row('B', { kind: 'future-kind' })] });
  assert.equal(g.eventCount, 2); assert.equal(node(g, 'other').count, 1);
});
test('activity never proves live AI or a decision', () => {
  const g = projectGraph({ items: [row('A')], info: { working: true }, receivedAt: 1000, now: 1001 });
  assert.equal(node(g, 'study').status, 'Recorded activity');
  assert.equal(node(g, 'decision').status, 'Not connected');
});
test('missing usage remains unknown, zero remains zero', () => {
  assert.equal(projectGraph({}).usage.calls, null);
  assert.deepEqual(projectGraph({ info: { today: {}, tokens: 0, spent_usd: 0 } }).usage,
    { calls: 0, tokens: 0, estimatedUsd: 0 });
  assert.equal(projectGraph({ info: { today: { study: '12' } } }).usage.calls, null);
});
test('failure and clock expiry mark retained data stale', () => {
  const input = { items: [row('A')], receivedAt: 1000, now: 1001 };
  assert.equal(projectGraph(input).stale, false);
  assert.equal(projectGraph({ ...input, failed: true }).stale, true);
  assert.equal(projectGraph({ ...input, now: 46001 }).stale, true);
});
test('bounded feed does not include invalid records', () => {
  const rows = Array.from({ length: 400 }, (_, i) => row('A', { t: i }));
  assert.equal(normalizeEvents([...rows, null, { t: NaN }]).length, 300);
  assert.equal(normalizeEvents(rows)[0].t, 399);
});
test('model retains text as data, ignores untyped steps', () => {
  const e = normalizeEvents([row('A', { text: '<img onerror=alert(1)>', steps: [null, 'check'] })])[0];
  assert.equal(e.text, '<img onerror=alert(1)>'); assert.deepEqual(e.steps, ['check']);
});
test('projection is deterministic and does not mutate API objects', () => {
  const input = { items: [row('A')], now: 1000 }; const before = JSON.stringify(input);
  assert.deepEqual(projectGraph(input), projectGraph(input)); assert.equal(JSON.stringify(input), before);
});

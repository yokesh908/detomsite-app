const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const source = fs.readFileSync(path.resolve(__dirname, '../src/utils/operations.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
const loaded = { exports: {} }
new Function('module', 'exports', compiled)(loaded, loaded.exports)
const { operationInsights, orderGroup } = loaded.exports
const now = Date.parse('2026-09-17T12:00:00Z')
const row = (id, status, value, age = 3600000, shop = 'Cafe') => ({ id, status, value, shop, created_at: new Date(now - age).toISOString() })

test('empty metrics are finite zero values', () => {
  const s = operationInsights([], 7, now)
  for (const k of ['count', 'completed', 'cancelled', 'average', 'completedValue', 'completionRate', 'active', 'waiting', 'ready']) assert.equal(s[k], 0)
  assert.deepEqual(s.shops, [])
})

test('completed value excludes unpaid, cancelled and rejected orders', () => {
  const s = operationInsights([
    row('a', 'Completed', 100), row('b', 'Delivered', 200),
    row('c', 'Cancelled', 500), row('d', 'Rejected', 700), row('e', 'Pending Payment', 900),
  ], 7, now)
  assert.equal(s.completedValue, 300)
  assert.equal(s.average, 150)
  assert.equal(s.completionRate, 40)
  assert.equal(s.cancelled, 2)
  assert.equal(s.active, 1)
  assert.equal(s.waiting, 0)
})

test('date range excludes invalid and future dates but does not hide backlog', () => {
  const s = operationInsights([
    row('old', 'Preparing', 100, 10 * 86400000),
    row('future', 'Completed', 100, -1),
    { ...row('invalid', 'Completed', 100), created_at: 'invalid' },
    row('boundary', 'Delivered', 50, 86400000),
    row('ready', 'Ready', 60),
  ], 1, now)
  assert.equal(s.count, 2)
  assert.equal(s.completedValue, 50)
  assert.equal(s.active, 2)
  assert.equal(s.waiting, 1)
  assert.equal(s.ready, 1)
})

test('invalid monetary values do not poison metrics and shops sort by completed value', () => {
  const s = operationInsights([
    row('a', 'Completed', NaN), row('b', 'Delivered', -100),
    row('c', 'Completed', Infinity), row('d', 'Completed', 150, 1000, 'Kitchen'),
  ], 7, now)
  assert.equal(s.completedValue, 150)
  assert.equal(s.average, 37.5)
  assert.equal(s.shops[0].name, 'Kitchen')
  assert.equal(s.shops[1].completedValue, 0)
})

test('history groups delivered and rejected orders consistently', () => {
  for (const status of ['Delivered', 'Completed']) assert.equal(orderGroup(status), 'completed')
  for (const status of ['Cancelled', 'Rejected']) assert.equal(orderGroup(status), 'cancelled')
  for (const status of ['Pending Payment', 'Pending', 'Confirmed', 'Preparing', 'Ready']) assert.equal(orderGroup(status), 'active')
})

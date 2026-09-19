const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

function storage() {
  const data = new Map()
  return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, String(value)), removeItem: key => data.delete(key) }
}

function browser() {
  const localStorage = storage()
  const sessionStorage = storage()
  const window = new EventTarget()
  window.location = { href: '', reload() {} }
  window.setInterval = setInterval
  const document = new EventTarget()
  document.hidden = true // no timers or network polling in these tests
  const modules = new Map()
  const context = vm.createContext({ localStorage, sessionStorage, window, document, Event, console, setInterval, clearInterval })
  function load(relative) {
    const filename = path.resolve(__dirname, '../src', relative)
    if (modules.has(filename)) return modules.get(filename).exports
    const module = { exports: {} }
    modules.set(filename, module)
    const source = fs.readFileSync(filename, 'utf8').replace('import.meta.env.VITE_API_URL', 'undefined')
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
    const run = vm.runInContext(`(function(require, module, exports) { ${compiled}\n})`, context)
    run(name => name.startsWith('.') ? load(path.relative(path.resolve(__dirname, '../src'), path.resolve(path.dirname(filename), name + '.ts'))) : require(name), module, module.exports)
    return module.exports
  }
  return { localStorage, sessionStorage, load }
}

const alice = { role: 'student', email: 'alice@example.test', name: 'Alice', phone: '9000000001' }
const bob = { role: 'student', email: 'bob@example.test', name: 'Bob', phone: '9000000002' }

test('logout clears the identity, credentials, cart and pending payment flag', () => {
  const b = browser()
  const session = b.load('utils/session.ts')
  b.localStorage.setItem('access_token', 'fake-alice-token')
  b.localStorage.setItem('refresh_token', 'fake-alice-refresh')
  b.localStorage.setItem('detomsite-cart', '[{"name":"Alice cart"}]')
  b.sessionStorage.setItem('payment_pending', 'true')
  session.saveLocalSession(alice)
  session.clearLocalSession()
  assert.equal(b.localStorage.getItem('access_token'), null)
  assert.equal(b.localStorage.getItem('refresh_token'), null)
  assert.equal(b.localStorage.getItem('detomsite-cart'), null)
  assert.equal(b.sessionStorage.getItem('payment_pending'), null)
  assert.equal(session.getLocalSession(), null)
})

test('a profile without a token is not an authenticated session', () => {
  const b = browser()
  b.localStorage.setItem('detomsite-session', JSON.stringify(bob))
  assert.equal(b.load('utils/session.ts').getLocalSession(), null)
})

test('late Alice API response is rejected after switching to Bob', async () => {
  const b = browser()
  const { api } = b.load('services/api.ts')
  b.localStorage.setItem('access_token', 'fake-alice-token')
  let finish
  let sent
  const dispatched = new Promise(resolve => { sent = resolve })
  api.defaults.adapter = config => new Promise(resolve => {
    finish = () => resolve({ config, data: [{ student_name: 'Alice' }], status: 200, statusText: 'OK', headers: {} })
    sent(config.headers.Authorization)
  })
  const response = api.get('/local/orders/parent')
  assert.equal(await dispatched, 'Bearer fake-alice-token')
  b.localStorage.setItem('access_token', 'fake-bob-token')
  finish()
  await assert.rejects(response, /session changed/i)
})


test('Bob never receives Alice cached notifications after account switch', async () => {
  const b = browser()
  b.localStorage.setItem('access_token', 'fake-alice-token')
  const session = b.load('utils/session.ts')
  session.saveLocalSession(alice)
  const { api } = b.load('services/api.ts')
  api.defaults.adapter = async config => ({ config, data: [{ id: 'alice-notice' }], status: 200, statusText: 'OK', headers: {} })
  const store = b.load('services/notifStore.ts')
  let latest = []
  const stop = store.subscribeNotifications(value => { latest = value })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(latest[0].id, 'alice-notice')
  stop()
  session.clearLocalSession()
  b.localStorage.setItem('access_token', 'fake-bob-token')
  session.saveLocalSession(bob)
  api.defaults.adapter = async config => ({ config, data: [], status: 200, statusText: 'OK', headers: {} })
  const seen = []
  const stopBob = store.subscribeNotifications(value => seen.push(...value))
  await new Promise(resolve => setImmediate(resolve))
  stopBob()
  assert.equal(seen.length, 0)
})


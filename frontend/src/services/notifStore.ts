import api from './api'
import { LocalNotification } from '../types/localApi'

/* A single shared, visibility-aware poller for student notifications. Layout
   and the customer dashboard both show the same bell/list, so polling once and
   pushing to every subscriber removes a duplicated request every cycle — and
   pausing while the tab is hidden stops background traffic entirely. */

let cache: LocalNotification[] = []
let timer: number | null = null
let subscriberCount = 0
let running = false
let inflight: Promise<void> | null = null

const listeners = new Set<(n: LocalNotification[]) => void>()
let ownerToken = localStorage.getItem('access_token')
let generation = 0

function resetForSession() {
  ownerToken = localStorage.getItem('access_token')
  generation++
  cache = []
  inflight = null
  listeners.forEach(l => l([]))
}

window.addEventListener('detomsite-session-changed', resetForSession)
window.addEventListener('storage', () => {
  if (ownerToken !== localStorage.getItem('access_token')) resetForSession()
})

async function poll() {
  if (ownerToken !== localStorage.getItem('access_token')) resetForSession()
  if (!ownerToken) return
  if (inflight) return inflight
  const started = generation
  inflight = (async () => {
    try {
      const r = await api.get<LocalNotification[]>('/local/notifications')
      if (started !== generation || ownerToken !== localStorage.getItem('access_token')) return
      cache = Array.isArray(r.data) ? r.data : []
      listeners.forEach(l => l(cache))
    } catch { /* keep the last known list */ }
  })().finally(() => { if (started === generation) inflight = null })
  return inflight
}

function stopTimer() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function startTimer() {
  if (timer !== null || document.hidden) return
  timer = window.setInterval(() => void poll(), 10000)
}

function refreshAndResume() {
  if (document.hidden) return
  void poll()
  startTimer()
}

function onVisibility() {
  if (document.hidden) {
    stopTimer()
  } else {
    refreshAndResume()
  }
}

function start() {
  subscriberCount++
  // `running` guards the GLOBAL listeners + poll loop, which must be created
  // exactly once per full lifecycle. Its only job is to prevent double-wiring
  // when a second subscriber joins; stop() tears everything down when the last
  // subscriber leaves — even if the timer never started (e.g. tab was hidden).
  if (running) return
  running = true
  void poll()
  startTimer()
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('focus', refreshAndResume)
}

function stop() {
  subscriberCount = Math.max(0, subscriberCount - 1)
  if (subscriberCount || !running) return
  running = false
  stopTimer()
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('focus', refreshAndResume)
}

export function subscribeNotifications(cb: (n: LocalNotification[]) => void): () => void {
  if (ownerToken !== localStorage.getItem('access_token')) resetForSession()
  listeners.add(cb)
  cb(cache)
  start()
  return () => {
    listeners.delete(cb)
    stop()
  }
}
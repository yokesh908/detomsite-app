import { useCallback, useEffect, useRef } from 'react'

/**
 * Visibility-aware polling hook shared by every portal screen.
 *
 * Why this exists: every portal used to run `setInterval(load, N)` on a fixed
 * cadence, even while the tab was sitting minimised in the background — so a
 * student/shopkeeper/admin with a few tabs open was hammering the API in
 * background tabs they weren't even looking at'amaha.
 *
 * This hook:
 *  - Fetches immediately on mount and whenever `deps` change.
 *  - Re-fetches every `intervalMs` ONLY while the document is visible.
 *  - When the tab is hidden the timer is cleared (no background hammering) and
 *    reinstated the moment the tab becomes visible again.
 *  - On becoming visible (visibilitychange/focus) it debounces by 300ms, then
 *    re-fetches instantly and resumes the normal cadence — so the screen is
 *    never stale after switching back, without ever firing a burst.
 *  - Keeps the latest `load` in a ref so an interval started by an older render
 *    still calls the newest load (no stale closures).
 *
 * Returns `{ pollNow }` — call it right after a mutation to refresh that screen
 * immediately and restart the timer.
 */
export function usePolling(
  load: () => void | Promise<void>,
  intervalMs: number,
  deps: readonly unknown[] = [],
) {
  const loadRef = useRef(load)
  loadRef.current = load

  const timerRef = useRef<number | null>(null)
  const focusTimerRef = useRef<number | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const clearFocusTimer = useCallback(() => {
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current)
      focusTimerRef.current = null
    }
  }, [])

  const pollNow = useCallback(() => {
    void loadRef.current()
  }, [])

  const start = useCallback(() => {
    if (timerRef.current !== null || document.hidden) return
    timerRef.current = window.setInterval(() => {
      if (document.hidden) return
      void loadRef.current()
    }, intervalMs)
  }, [intervalMs])

  const onVisible = useCallback(() => {
    clearTimer()
    clearFocusTimer()
    // Debounce rapid focus/visibility flips (alt-tab bursts) so we never fire a
    // burst of requests — a single instant refresh, then resume pacing.
    focusTimerRef.current = window.setTimeout(() => {
      focusTimerRef.current = null
      pollNow()
      start()
    }, 300)
  }, [clearTimer, clearFocusTimer, pollNow, start])

  useEffect(() => {
    clearTimer()
    clearFocusTimer()
    // Mounting (or a deps change) in an already-hidden tab must not fire a
    // request or start a timer — the visibility handler resumes everything
    // the instant the user comes back.
    if (!document.hidden) {
      pollNow()
      start()
    }

    const onVis = () => {
      if (document.hidden) {
        clearTimer()
        clearFocusTimer()
      } else {
        onVisible()
      }
    }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('focus', onVis)

    return () => {
      clearTimer()
      clearFocusTimer()
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('focus', onVis)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollNow, start, clearTimer, clearFocusTimer, onVisible, ...deps])

  return { pollNow }
}

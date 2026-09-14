/* Only overwrite state when the value actually changed, so a poll that
   returned identical data causes ZERO re-render — the dashboard or list stays
   untouched instead of re-rendering (and visibly "refreshing") the whole page. */
export function same<T>(prev: T | null, next: T): boolean {
  if (prev === next) return true
  try {
    return JSON.stringify(prev) === JSON.stringify(next)
  } catch {
    return false
  }
}
export interface InsightOrder {
  id: string
  status: string
  created_at: string
  value: number
  shop: string
}

export function orderGroup(status: string): 'active' | 'completed' | 'cancelled' {
  if (['Delivered', 'Completed'].includes(status)) return 'completed'
  if (['Cancelled', 'Rejected'].includes(status)) return 'cancelled'
  return 'active'
}

export function operationInsights(orders: InsightOrder[], days: number, now = Date.now()) {
  const cutoff = now - days * 86400000
  const rows = orders.filter(o => {
    const date = Date.parse(o.created_at)
    return Number.isFinite(date) && date >= cutoff && date <= now
  })
  const completed = rows.filter(o => orderGroup(o.status) === 'completed')
  const cancelled = rows.filter(o => orderGroup(o.status) === 'cancelled')
  const valueOf = (o: InsightOrder) => Number.isFinite(Number(o.value)) ? Math.max(0, Number(o.value)) : 0
  const completedValue = completed.reduce((sum, o) => sum + valueOf(o), 0)
  const shops = new Map<string, { name: string; orders: number; completedValue: number }>()
  rows.forEach(o => {
    const entry = shops.get(o.shop) || { name: o.shop, orders: 0, completedValue: 0 }
    entry.orders++
    if (orderGroup(o.status) === 'completed') entry.completedValue += valueOf(o)
    shops.set(o.shop, entry)
  })
  // Workload includes older orders too: a date filter must not hide a backlog.
  const active = orders.filter(o => orderGroup(o.status) === 'active')
  const waiting = active.filter(o => ['Pending', 'Confirmed', 'Accepted', 'Preparing'].includes(o.status)
    && Number.isFinite(Date.parse(o.created_at)) && now - Date.parse(o.created_at) >= 20 * 60000)
  return {
    count: rows.length, completed: completed.length, cancelled: cancelled.length,
    completedValue, average: completed.length ? completedValue / completed.length : 0,
    completionRate: rows.length ? Math.round(completed.length / rows.length * 100) : 0,
    active: active.length, waiting: waiting.length,
    ready: active.filter(o => o.status === 'Ready').length,
    shops: [...shops.values()].sort((a, b) => b.completedValue - a.completedValue),
  }
}

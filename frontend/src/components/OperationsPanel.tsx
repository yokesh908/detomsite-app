import { useState } from 'react'
import { InsightOrder, operationInsights } from '../utils/operations'

const money = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)

export function OperationsPanel({ orders, partner = false }: { orders: InsightOrder[]; partner?: boolean }) {
  const [days, setDays] = useState(7)
  const stats = operationInsights(orders, days)
  return (
    <section className="mb-6 rounded-card border border-primary-light/50 bg-gradient-to-br from-emerald-50 to-white p-4 sm:p-5" aria-label="Operations insights">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-primary-dark">{partner ? 'Partner performance & tips' : 'Operations overview'}</h2>
          <p className="text-xs text-gray-600">Based on loaded records only; not an exhaustive financial report. Rolling periods.</p>
        </div>
        <label className="text-sm font-semibold text-primary">Period
          <select value={days} onChange={e => setDays(Number(e.target.value))} className="ml-2 rounded-lg border border-gray-200 bg-white p-2">
            <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option>
          </select>
        </label>
      </div>
      <div className="my-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ['Orders in period', stats.count], ['Completed order value', money(stats.completedValue)],
          ['Average completed order', money(stats.average)], ['Completion rate', `${stats.completionRate}%`],
        ].map(([label, value]) => <div key={label} className="rounded-btn bg-white p-3 shadow-sm"><p className="text-xs text-gray-500">{label}</p><p className="mt-1 text-xl font-bold text-primary-dark">{value}</p></div>)}
      </div>
      <p className="text-xs text-gray-500">Completed includes delivered orders. Value is before refunds, fees and settlement adjustments—not paid-out earnings. {stats.cancelled} cancelled/rejected in period.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3"><p className="font-bold text-amber-800">{stats.waiting} waiting 20+ minutes</p><p className="text-xs text-amber-800">Review acceptance and preparation delays. This is an attention threshold, not a delivery promise.</p></div>
        <div className="rounded-lg border border-emerald-200 bg-white p-3"><p className="font-bold text-primary">{stats.ready} ready for pickup</p><p className="text-xs text-gray-600">Check packing and handoff before marking delivered.</p></div>
        <div className="rounded-lg border border-gray-200 bg-white p-3"><p className="font-bold text-primary">{stats.active} active orders</p><p className="text-xs text-gray-600">{partner ? 'Keep item availability accurate. Pause new orders if the kitchen cannot keep up.' : 'Review payment, refund and complaint queues using the tabs below.'}</p></div>
      </div>
      {!partner && <div className="mt-4 overflow-x-auto">
        <h3 className="mb-2 text-sm font-bold text-primary">Shop performance · loaded single-shop orders</h3>
        {stats.shops.length ? <table className="w-full text-left text-sm"><thead><tr className="text-gray-500"><th scope="col" className="py-2">Shop</th><th scope="col">Orders</th><th scope="col">Completed value</th></tr></thead><tbody>{stats.shops.slice(0, 5).map(shop => <tr key={shop.name} className="border-t border-gray-100"><td className="py-2">{shop.name}</td><td>{shop.orders}</td><td>{money(shop.completedValue)}</td></tr>)}</tbody></table> : <p className="text-sm text-gray-500">No orders in this period.</p>}
      </div>}
    </section>
  )
}

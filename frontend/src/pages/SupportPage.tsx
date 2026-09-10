import { FormEvent, useEffect, useState } from 'react'
import api from '../services/api'
import { LocalTicket } from '../types/localApi'
import { getLocalSession } from '../utils/session'
import { PhoneInput } from '../components/PhoneInput'

export function SupportPage() {
  const session = getLocalSession()
  const [tickets, setTickets] = useState<LocalTicket[]>([])
  const [form, setForm] = useState({ name: session?.name || '', email: session?.email || '', phone_number: '', category: 'order_issue', title: '', description: '' })
  const [message, setMessage] = useState('')

  useEffect(() => { api.get<LocalTicket[]>('/local/tickets').then(r => setTickets(r.data)).catch(() => setTickets([])) }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await api.post<LocalTicket>('/local/tickets', form)
    setTickets(curr => [r.data, ...curr]); setMessage(`Ticket ${r.data.ticket_number} created`)
    setForm(f => ({ ...f, phone_number: '', title: '', description: '' }))
  }

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="mb-6 text-2xl font-bold text-primary-dark">Support</h1>
        <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
          <form onSubmit={submit} className="rounded-btn bg-white p-6 shadow-card">
            <h2 className="mb-4 text-lg font-bold text-primary">Create Ticket</h2>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <input value={form.name} onChange={e => setForm({...form, name: e.target.value})}
                  className="rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Name" required />
                <PhoneInput value={form.phone_number} onChange={v => setForm({...form, phone_number: v})} placeholder="10-digit mobile" required />
              </div>
              <input value={form.email} onChange={e => setForm({...form, email: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Email" type="email" required />
              <select value={form.category} onChange={e => setForm({...form, category: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-primary focus:shadow-emerald-sm">
                <option value="order_issue">Order Issue</option>
                <option value="payment_issue">Payment Issue</option>
                <option value="refund_issue">Refund Issue</option>
                <option value="vendor_complaint">Vendor Complaint</option>
                <option value="technical_issue">Technical Issue</option>
              </select>
              <input value={form.title} onChange={e => setForm({...form, title: e.target.value})}
                className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Title" required />
              <textarea value={form.description} onChange={e => setForm({...form, description: e.target.value})}
                className="min-h-[120px] w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-primary focus:shadow-emerald-sm" placeholder="Describe your issue" required />
              <button className="rounded-btn bg-primary px-5 py-2.5 text-sm font-bold text-white shadow-gold-sm hover:bg-primary-dark">Submit Ticket</button>
              {message && <p className="rounded-lg bg-primary-light/30 border border-primary-light/50 px-4 py-2 text-sm font-medium text-primary">{message}</p>}
            </div>
          </form>
          <div className="rounded-btn bg-white p-6 shadow-card">
            <h2 className="mb-4 text-lg font-bold text-primary">Recent Tickets</h2>
            <div className="space-y-3">
              {tickets.map(t => (
                <div key={t.id} className="rounded-btn bg-gray-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="font-semibold text-primary-dark">{t.ticket_number} · {t.title}</p><p className="text-xs text-gray-500">{t.category} · {t.phone_number}</p></div>
                    <span className="shrink-0 rounded-lg bg-primary-light/30 px-2 py-0.5 text-xs font-bold text-primary">{t.status}</span>
                  </div>
                  <p className="mt-2 text-sm text-gray-500">{t.description}</p>
                </div>
              ))}
              {tickets.length === 0 && <p className="text-sm text-gray-400">No tickets yet</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

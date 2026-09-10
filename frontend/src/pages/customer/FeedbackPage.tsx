import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import { LocalFeedback } from '../../types/localApi'
import { getLocalSession } from '../../utils/session'

const CATEGORIES = [
  { id: 'Bug', label: 'Bug', icon: '🐞', desc: 'Something is broken', cls: 'from-red-500 to-rose-600', active: 'border-red-300 bg-red-50 text-red-700' },
  { id: 'Improvement', label: 'Improvement', icon: '💡', desc: 'Make it better', cls: 'from-amber-400 to-orange-500', active: 'border-amber-300 bg-amber-50 text-gold-dark' },
  { id: 'Suggestion', label: 'Suggestion', icon: '✨', desc: 'An idea for us', cls: 'from-emerald-500 to-teal-600', active: 'border-emerald-300 bg-primary-light/30 text-primary' },
  { id: 'Other', label: 'Other', icon: '💬', desc: 'Anything else', cls: 'from-sky-500 to-indigo-600', active: 'border-sky-300 bg-sky-50 text-sky-800' },
] as const

const STATUS_STYLES: Record<string, string> = {
  'Open': 'bg-amber-50 text-gold-dark border-gold-light/60',
  'In Review': 'bg-sky-50 text-sky-700 border-sky-200',
  'Fixed': 'bg-primary-light/30 text-primary border-primary-light/50',
  "Won't Fix": 'bg-gray-100 text-gray-500 border-gray-200',
}

/* One-tap chips that prefill "Where did you find it?" — speeds up reporting. */
const QUICK_PAGES = ['Shops page', 'Checkout / Payment', 'Order tracking', 'Login / Register', 'Cart', 'This feedback page']

function fmtDate(raw?: string): string {
  if (!raw) return ''
  const d = new Date(raw.replace(' ', 'T'))
  if (isNaN(d.getTime())) return raw.slice(0, 16)
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

export function FeedbackPage() {
  const session = getLocalSession()
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]['id']>('Bug')
  const [subject, setSubject] = useState('')
  const [page, setPage] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState<LocalFeedback | null>(null)
  const [error, setError] = useState('')
  const [mine, setMine] = useState<LocalFeedback[]>([])

  const loadMine = () => {
    api.get<LocalFeedback[]>('/local/feedback/mine')
      .then(res => setMine(res.data || []))
      .catch(() => setMine([]))
  }
  useEffect(loadMine, [])

  const stats = useMemo(() => ({
    total: mine.length,
    open: mine.filter(f => f.status === 'Open').length,
    inReview: mine.filter(f => f.status === 'In Review').length,
    fixed: mine.filter(f => f.status === 'Fixed').length,
  }), [mine])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(''); setSent(null)
    if (subject.trim().length < 3) { setError('Give your contribution a short bug title (min 3 characters).'); return }
    if (message.trim().length < 5) { setError('Tell us a little more — what happened (min 5 characters)?'); return }
    setSending(true)
    try {
      const res = await api.post<LocalFeedback>('/local/feedback', {
        category,
        subject: subject.trim(),
        message: message.trim(),
        page: page.trim(),
        source: 'User',
        name: session?.name || '',
        email: session?.email || '',
      })
      setSent(res.data)
      setSubject(''); setPage(''); setMessage(''); setCategory('Bug')
      loadMine()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not send your report. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="min-h-screen bg-white">
      {/* Hero — the "test our site" notice the user sees after logging in */}
      <section className="border-b border-primary-light/30/80 bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 text-white">
        <div className="mx-auto max-w-5xl px-4 py-10 md:py-14">
          <p className="mb-3 inline-flex items-center gap-2 rounded-pill bg-white/10 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.25em] text-primary/50">
            <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-pill bg-gold-light opacity-75" /><span className="relative inline-flex h-2 w-2 rounded-pill bg-gold-light" /></span>
            Community Testing
          </p>
          <h1 className="text-3xl font-black tracking-tight md:text-4xl">Help us test DETOMSITE 🧪</h1>
          <p className="mt-3 max-w-2xl text-base font-medium text-primary/50/90">
            This is a <span className="font-bold text-gold">testing build</span> — if you spot a bug, or think something
            could work better, tell us! Every contribution goes straight to the admin team so we can fix the site before it goes live.
          </p>
          <div className="mt-5 flex flex-wrap gap-3 text-sm font-semibold text-primary/50">
            <span className="rounded-pill bg-white/10 px-3 py-1.5">🐞 Report bugs you find</span>
            <span className="rounded-pill bg-white/10 px-3 py-1.5">💡 Suggest improvements</span>
            <span className="rounded-pill bg-white/10 px-3 py-1.5">👀 Track your contributions</span>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-5xl px-4 py-8">
        {/* Personal stats */}
        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { l: 'Your reports', v: stats.total, cls: 'text-primary-dark' },
            { l: 'Open', v: stats.open, cls: 'text-gold-dark' },
            { l: 'In review', v: stats.inReview, cls: 'text-sky-600' },
            { l: 'Fixed', v: stats.fixed, cls: 'text-primary' },
          ].map(s => (
            <div key={s.l} className="rounded-card border border-primary-light/30 bg-white p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
              <p className="text-xs font-semibold text-gray-500">{s.l}</p>
              <p className={`mt-1 text-2xl font-black ${s.cls}`}>{s.v}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr]">
          {/* ─── Submit form ─── */}
          <section className="rounded-[28px] border border-primary-light/30 bg-white p-6 shadow-[0_14px_42px_rgba(15,118,110,0.08)] md:p-8">
            <h2 className="text-xl font-bold text-primary-dark">Make a contribution</h2>
            <p className="mt-1 text-sm font-medium text-gray-500">A bug you found, or an idea to improve the site — the admin receives it instantly.</p>

            {sent && (
              <div className="mt-5 flex items-start gap-3 rounded-card border border-primary-light/50 bg-primary-light/30 p-4 animate-fade-in">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-pill bg-primary text-white">✓</span>
                <div>
                  <p className="font-bold text-primary">Contribution sent — thank you!</p>
                  <p className="mt-0.5 text-sm font-medium text-primary">The admin team will review it. Track it in “Your contributions” below.</p>
                </div>
                <button type="button" onClick={() => setSent(null)} className="ml-auto rounded-pill p-1 text-primary hover:bg-primary-light">✕</button>
              </div>
            )}
            {error && (
              <div className="mt-5 flex items-start gap-3 rounded-card border border-red-200 bg-red-50 p-4 animate-fade-in">
                <span className="mt-0.5">⚠️</span>
                <p className="text-sm font-semibold text-red-700">{error}</p>
              </div>
            )}

            <form onSubmit={submit} className="mt-6 space-y-5">
              <div>
                <label className="mb-2 block text-xs font-bold uppercase tracking-wide text-gray-500">Type</label>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  {CATEGORIES.map(c => (
                    <button key={c.id} type="button" onClick={() => setCategory(c.id)}
                      className={`group rounded-card border-2 p-3 text-left transition-all hover:-translate-y-0.5 ${
                        category === c.id ? `${c.active} border-2 shadow-emerald-sm` : 'border-gray-100 bg-white hover:border-primary-light/50'
                      }`}>
                      <span className="block text-xl">{c.icon}</span>
                      <span className={`mt-1 block text-sm font-bold ${category === c.id ? '' : 'text-gray-600'}`}>{c.label}</span>
                      <span className={`mt-0.5 block text-[11px] font-medium leading-tight ${category === c.id ? 'opacity-80' : 'text-gray-400'}`}>{c.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label htmlFor="fb-subject" className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">
                  {category === 'Bug' ? 'Bug title' : 'Title'}
                </label>
                <input id="fb-subject" value={subject} onChange={e => setSubject(e.target.value)} maxLength={150}
                  placeholder="Short title for your bug or idea, e.g. “Payment page won’t load on iPhone”"
                  className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm" />
                <p className="mt-1 text-right text-xs font-medium text-gray-400">{subject.length}/150</p>
              </div>

              <div>
                <label htmlFor="fb-page" className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">
                  Where did you find it? <span className="font-medium normal-case text-gray-400">(optional)</span>
                </label>
                <div className="relative">
                  <input id="fb-page" value={page} onChange={e => setPage(e.target.value)} maxLength={200}
                    placeholder="e.g. Shops page, Checkout, Order tracking…"
                    className="w-full rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm" />
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {QUICK_PAGES.map(q => (
                    <button key={q} type="button" onClick={() => setPage(q)}
                      className={`rounded-pill border px-2.5 py-1 text-[11px] font-semibold transition-all hover:-translate-y-0.5 ${
                        page === q ? 'border-emerald-400 bg-primary-light/30 text-primary shadow-emerald-sm' : 'border-gray-200 bg-white text-gray-500 hover:border-emerald-300 hover:text-primary'
                      }`}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                {/* The label follows the category — it's only a "bug" when the
                    student picked the Bug type; improvements/suggestions get
                    their own wording (contributions, not just bugs). */}
                <label htmlFor="fb-message" className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-gray-500">
                  {category === 'Bug' ? 'What is the bug?' : category === 'Improvement' ? 'Describe the improvement' : category === 'Suggestion' ? 'Describe your suggestion' : 'Describe it'}
                </label>
                <textarea id="fb-message" value={message} onChange={e => setMessage(e.target.value)} maxLength={2000} rows={4}
                  placeholder={category === 'Bug'
                    ? 'Describe the bug — what happened, what you expected, and how to reproduce it…'
                    : 'Tell us more — what would you like to see changed, and why?'}
                  className="w-full resize-y rounded-btn border-2 border-gray-200 bg-white px-4 py-3 text-sm text-gray-900 placeholder-gray-400 outline-none transition-all focus:border-primary focus:shadow-emerald-sm" />
                <p className="mt-1 text-right text-xs font-medium text-gray-400">{message.length}/2000</p>
              </div>
              <button type="submit" disabled={sending}
                className="group flex w-full items-center justify-center gap-2 rounded-btn bg-primary px-6 py-3.5 text-base font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:bg-primary-dark hover:shadow-xl active:scale-[0.98] disabled:opacity-40 disabled:hover:shadow-lg">
                {sending ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z" /></svg>
                    Sending…
                  </>
                ) : (
                  <>
                    Send contribution
                    <svg className="h-4 w-4 transition-transform group-hover:translate-x-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 14 0M13 6l6 6-6 6" /></svg>
                  </>
                )}
              </button>
              <p className="text-center text-[11px] font-medium text-gray-400">Reaches the admin team instantly — every report helps us improve the site.</p>
            </form>
          </section>

          {/* ─── Your contributions ─── */}
          <section className="rounded-[28px] border border-primary-light/30 bg-white p-6 shadow-[0_14px_42px_rgba(15,118,110,0.08)] md:p-8">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xl font-bold text-primary-dark">Your contributions</h2>
              <span className="rounded-pill bg-primary-light/30 px-3 py-1 text-xs font-bold text-primary">{mine.length}</span>
            </div>
            <p className="mb-4 text-sm font-medium text-gray-500">Everything you've contributed while testing — the team updates the status as they work through them.</p>

            {mine.length === 0 ? (
              <div className="rounded-card border border-dashed border-primary-light/50 bg-primary-light/30/40 p-8 text-center">
                <span className="text-3xl">📭</span>
                <p className="mt-2 font-bold text-primary">No reports yet</p>
                <p className="mt-1 text-sm font-medium text-gray-500">Found something? Send your first report and it will show up here.</p>
              </div>
            ) : (
              <div className="max-h-[560px] space-y-3 overflow-y-auto pr-1">
                {mine.map(f => (
                  <div key={f.id} className="group rounded-card border border-gray-100 bg-white p-4 shadow-card transition-all hover:-translate-y-0.5 hover:border-primary-light/50 hover:shadow-card-hover">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{CATEGORIES.find(c => c.id === f.category)?.icon || '💬'}</span>
                        <p className="font-bold text-gray-900">{f.subject}</p>
                      </div>
                      <span className={`shrink-0 rounded-pill border px-2.5 py-0.5 text-[11px] font-bold ${STATUS_STYLES[f.status] || STATUS_STYLES['Open']}`}>{f.status}</span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-gray-600">{f.message}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-gray-400">
                      {f.page && <span className="rounded-pill bg-gray-50 px-2 py-0.5">📍 {f.page}</span>}
                      <span className="rounded-pill bg-gray-50 px-2 py-0.5">🕒 {fmtDate(f.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-5 rounded-card bg-primary-light/30 p-4 text-sm font-medium text-primary">
              💬 Need urgent help with an order instead?{' '}
              <Link to="/support" className="font-bold text-primary underline decoration-emerald-300 underline-offset-2 hover:text-primary-dark">Open a support ticket</Link>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

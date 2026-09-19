import React, { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LocalNotification } from '../types/localApi'
import { getCart } from '../utils/cart'
import { clearLocalSession, getLocalSession, LocalSession } from '../utils/session'
import { subscribeNotifications } from '../services/notifStore'
import { InstallPwaCard } from './InstallPwaCard'

const SEEN = 'detomsite-seen-completed'
function getSeen(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN) || '[]') as string[]) }
  catch { return new Set() }
}
function markSeen(id: string) {
  const s = getSeen(); s.add(id); localStorage.setItem(SEEN, JSON.stringify([...s]))
}

interface LayoutProps { children: React.ReactNode; className?: string }

export const MainLayout: React.FC<LayoutProps> = ({ children, className = '' }) => {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [session, setSession] = useState<LocalSession | null>(() => getLocalSession())
  const [cartCount, setCartCount] = useState(() => getCart().length)
  const [notifications, setNotifications] = useState<LocalNotification[]>([])
  const [notifOpen, setNotifOpen] = useState(false)
  const [completionToast, setCompletionToast] = useState<LocalNotification | null>(null)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    const sync = () => setCartCount(getCart().length)
    window.addEventListener('detomsite-cart-updated', sync)
    return () => window.removeEventListener('detomsite-cart-updated', sync)
  }, [])

  /* Re-read the session on every navigation — RoleGate/phone login writes to
     localStorage after this component first mounted, so a persist-only read
     left the top navbar showing the pre-login state. */
  useEffect(() => {
    setSession(getLocalSession())
  }, [location.pathname])

  useEffect(() => {
    return subscribeNotifications(list => {
      setNotifications(list)
      const latest = list.find(n => n.status === 'Completed')
      if (latest && !getSeen().has(latest.id)) setCompletionToast(prev => prev?.id === latest.id ? prev : latest)
    })
  }, [])

  const logout = () => { clearLocalSession(); window.location.href = '/' }
  const closeToast = () => { if (completionToast) markSeen(completionToast.id); setCompletionToast(null) }
  /* Back button: don't leave the app when the user deep-linked into a page. */
  const goBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx
    if (idx != null && idx > 0) navigate(-1)
    else navigate('/')
  }

  const navItems = [
    { path: '/', label: 'Home' },
    { path: '/shops', label: 'Shops' },
    ...(session?.role === 'admin' ? [{ path: '/admin-dashboard', label: 'Dashboard' }]
      : session?.role === 'shopkeeper' ? [{ path: '/shopkeeper-dashboard', label: 'Dashboard' }]
      : [{ path: '/customer-dashboard', label: 'Dashboard' }, { path: '/feedback', label: 'Feedback' }]),
    { path: '/cart', label: `Cart${cartCount ? ` (${cartCount})` : ''}` },
  ]

  return (
    <div className={`min-h-screen bg-transparent ${className}`}>
      <nav className="sticky top-0 z-50 border-b border-primary-light/30/80 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-10 w-10 items-center justify-center rounded-card bg-gradient-to-br from-emerald-800 to-emerald-600 text-base font-black text-gold shadow-lg shadow-emerald-900/20">D</span>
            <span className="text-lg font-black tracking-wide text-primary-dark max-sm:hidden">DETOMSITE</span>
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            {navItems.map(item => (
              <Link key={item.path} to={item.path}
                className={`rounded-pill px-4 py-2 text-sm font-semibold transition-all ${
                  location.pathname === item.path ? 'bg-primary-dark text-white shadow-lg shadow-emerald-900/15' : 'text-slate-600 hover:bg-primary-light/30 hover:text-primary'
                }`}>{item.label}</Link>
            ))}

            <div className="relative">
              <button type="button" onClick={() => setNotifOpen(!notifOpen)}
                className="rounded-pill px-3 py-2 text-sm font-semibold text-slate-600 transition-all hover:bg-primary-light/30 hover:text-primary">
                🔔{notifications.length > 0 && <span className="ml-1 text-xs font-bold text-gold-dark">{notifications.length}</span>}
              </button>
              {notifOpen && (
                <div className="absolute right-0 top-12 z-50 w-80 rounded-card border border-primary-light/30 bg-white p-3 shadow-2xl shadow-emerald-900/10">
                  <h3 className="mb-2 px-1 text-sm font-bold text-primary">Notifications</h3>
                  <div className="max-h-72 space-y-1.5 overflow-y-auto">
                    {notifications.map(n => (
                      <Link key={n.id} to={n.order_id ? `/order-result/${n.order_id}` : '/customer-dashboard'} onClick={() => setNotifOpen(false)}
                        className="block rounded-btn bg-primary-light/30/70 px-3 py-2.5 text-sm transition-colors hover:bg-primary-light">
                        <p className="font-semibold text-primary">{n.title}</p>
                        <p className="text-xs font-medium text-slate-500">{n.message}</p>
                      </Link>
                    ))}
                    {notifications.length === 0 && <p className="px-3 py-2 text-sm text-slate-400">No notifications</p>}
                  </div>
                </div>
              )}
            </div>

            {session && (
              <div className="ml-2 flex items-center gap-2 rounded-pill bg-primary-light/30 px-3 py-2 text-sm">
                <span className="font-medium text-primary">{session.email}</span>
                <button type="button" onClick={logout} className="text-xs font-bold text-primary hover:text-primary">Leave</button>
              </div>
            )}
          </div>

          <button className="rounded-pill p-2 text-slate-600 md:hidden" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? '✕' : '☰'}
          </button>
        </div>

        {mobileOpen && (
          <div className="border-t border-primary-light/30 bg-white/90 px-4 py-3 md:hidden">
            <div className="flex flex-col gap-1">
              {navItems.map(item => (
                <Link key={item.path} to={item.path} onClick={() => setMobileOpen(false)}
                  className={`rounded-btn px-4 py-2.5 text-sm font-semibold ${
                    location.pathname === item.path ? 'bg-primary-dark text-white' : 'text-slate-600 hover:bg-primary-light/30'
                  }`}>{item.label}</Link>
              ))}
              {session && <button type="button" onClick={logout}
                className="rounded-btn px-4 py-2.5 text-left text-sm font-semibold text-slate-500 hover:bg-primary-light/30">Leave · {session.email}</button>}
            </div>
          </div>
        )}
      </nav>

      {location.pathname !== '/' && (
        <div className="border-b border-primary-light/30 bg-white/70">
          <div className="mx-auto max-w-7xl px-4 py-2">
            <button type="button" onClick={goBack}
              className="inline-flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-sm font-semibold text-slate-600 transition-colors hover:bg-primary-light/30 hover:text-primary">← Back</button>
          </div>
        </div>
      )}

      {completionToast && (
        <div className="fixed right-4 top-20 z-[60] w-[360px] animate-slide-in-right rounded-card border border-primary-light/30 bg-white p-4 shadow-2xl shadow-emerald-900/10">
          <p className="text-xs font-bold uppercase tracking-[0.25em] text-primary">Order Update</p>
          <h3 className="mt-1 text-lg font-bold text-primary-dark">{completionToast.title}</h3>
          <p className="mt-1 text-sm font-medium text-slate-500">{completionToast.message}</p>
          <div className="mt-3 flex gap-2">
            <Link to={completionToast.order_id ? `/order-result/${completionToast.order_id}` : '/customer-dashboard'} onClick={closeToast}
              className="rounded-btn bg-primary px-4 py-2 text-sm font-bold text-white shadow-lg shadow-emerald-900/15 transition-colors hover:bg-primary-dark">View</Link>
            <button type="button" onClick={closeToast}
              className="rounded-btn border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-600 transition-colors hover:bg-slate-50">Close</button>
          </div>
        </div>
      )}

      <main>{children}</main>

      {location.pathname === '/shopkeeper-dashboard' && (
        <div className="mx-auto mt-8 max-w-7xl px-4">
          <InstallPwaCard />
        </div>
      )}

      <footer className="mt-16 border-t border-primary-light/30/80 bg-white/70">
        <div className="mx-auto max-w-7xl px-4 py-10">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-btn bg-gradient-to-br from-emerald-800 to-emerald-600 text-xs font-black text-gold">D</span>
              <span className="text-lg font-black text-primary-dark">DETOMSITE</span>
            </div>
            <p className="text-sm text-slate-500">© 2026. Campus food made simple.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
export default MainLayout

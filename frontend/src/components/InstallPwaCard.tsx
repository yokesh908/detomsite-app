import { useEffect, useState } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallPwaCard() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem('detomsite-pwa-dismissed') === '1' } catch { return false }
  })

  useEffect(() => {
    const handler = (event: Event) => {
      event.preventDefault()
      setDeferredPrompt(event as BeforeInstallPromptEvent)
    }
    const installedHandler = () => setInstalled(true)

    window.addEventListener('beforeinstallprompt', handler)
    window.addEventListener('appinstalled', installedHandler)

    return () => {
      window.removeEventListener('beforeinstallprompt', handler)
      window.removeEventListener('appinstalled', installedHandler)
    }
  }, [])

  const install = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    setDeferredPrompt(null)
    if (outcome === 'dismissed') {
      setDismissed(true)
      try { localStorage.setItem('detomsite-pwa-dismissed', '1') } catch {}
    }
  }

  const dismiss = () => {
    setDismissed(true)
    try { localStorage.setItem('detomsite-pwa-dismissed', '1') } catch {}
  }

  if (installed || dismissed) return null

  return (
    <div className="animate-fade-in rounded-[20px] border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-4 shadow-lg sm:rounded-[24px] sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-600 to-emerald-500 text-2xl shadow-lg shadow-emerald-900/15">
            📱
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600 sm:text-xs">Install App</p>
            <h3 className="mt-0.5 text-base font-black text-primary-dark sm:text-lg">Get the Shopkeeper App</h3>
            <p className="mt-0.5 text-xs text-slate-600 sm:text-sm">Manage orders, update status, and post announcements — right from your phone.</p>
          </div>
        </div>
        <div className="flex gap-2 sm:flex-col">
          <button
            onClick={install}
            className="flex-1 rounded-xl bg-gradient-to-r from-emerald-600 to-emerald-500 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-900/20 transition-all hover:shadow-xl hover:-translate-y-0.5 sm:flex-none"
          >
            Install Now
          </button>
          <button
            onClick={dismiss}
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-400 transition-colors hover:bg-gray-50 hover:text-gray-600"
          >
            Later
          </button>
        </div>
      </div>
      {/* Manual install instructions for iOS */}
      <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
        <p className="text-[10px] font-semibold text-amber-700 sm:text-xs">
          📲 <strong>iOS:</strong> Tap the Share button → "Add to Home Screen"
        </p>
      </div>
    </div>
  )
}

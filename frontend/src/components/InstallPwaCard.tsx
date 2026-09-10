import { useEffect, useState } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallPwaCard() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)

  useEffect(() => {
    const handler = (event: Event) => {
      event.preventDefault()
      setDeferredPrompt(event as BeforeInstallPromptEvent)
    }

    window.addEventListener('beforeinstallprompt', handler)
    window.addEventListener('appinstalled', () => setInstalled(true))

    return () => {
      window.removeEventListener('beforeinstallprompt', handler)
    }
  }, [])

  const install = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    setDeferredPrompt(null)
  }

  if (installed) return null

  return (
    <div className="rounded-[24px] border border-primary-light/30 bg-white/90 p-5 shadow-[0_14px_42px_rgba(15,118,110,0.12)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.25em] text-primary">Mobile experience</p>
          <h3 className="mt-1 text-lg font-black text-primary-dark">Install the shopkeeper app</h3>
          <p className="mt-1 text-sm text-slate-600">Use the app on your phone to manage orders, receive approvals, and stay connected with the campus portal.</p>
        </div>
        <button
          onClick={install}
          className="rounded-card bg-primary px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-emerald-900/15 hover:bg-primary-dark"
        >
          Install app
        </button>
      </div>
    </div>
  )
}

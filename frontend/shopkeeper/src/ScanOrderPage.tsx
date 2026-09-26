/* Scan orders — the student's order QR carries `DETOMSITE-ORDER:<order id>`.
   The shopkeeper scans it (or types the id) to pull the order up. "Download
   scanner" saves a standalone copy of this page so a shop can keep it on a
   home screen / a spare phone; the lookup still needs the network + a token, so
   the downloaded copy is a shortcut, not an offline database. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from './services/api'

/* Same message extraction the shop app uses; kept local so this page does not
   import from App.tsx (which would create a circular module). */
function apiError(e: any, fb = 'Request failed') {
  return e?.response?.data?.detail || e?.response?.data?.message || e?.message || fb
}

const SCAN_PLACEHOLDER = 'DETOMSITE-ORDER:… or the order id'

type BarcodeDetectorCtor = new (opts: { formats: string[] }) => {
  detect: (source: HTMLVideoElement) => Promise<{ rawValue?: string }[]>
}

export default function ScanOrderPage() {
  const navigate = useNavigate()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number | null>(null)
  const [manual, setManual] = useState('')
  const [scanMsg, setScanMsg] = useState('')
  const [scanErr, setScanErr] = useState('')
  const [cameraOn, setCameraOn] = useState(false)

  const stopCamera = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setCameraOn(false)
  }, [])

  useEffect(() => stopCamera, [stopCamera])

  const lookup = useCallback(async (code: string) => {
    const raw = (code || '').trim()
    if (!raw) { setScanErr('Enter or scan an order code'); return }
    setScanErr('')
    setScanMsg('Looking up the order…')
    try {
      const r = await api.get(`/vendor/orders/lookup?code=${encodeURIComponent(raw)}`)
      stopCamera()
      navigate('/mobile')
    } catch (err: any) {
      setScanErr(apiError(err, 'Order not found'))
      setScanMsg('')
    }
  }, [navigate, stopCamera])

  const startCamera = async () => {
    setScanErr('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setCameraOn(true)
      const tick = async () => {
        const video = videoRef.current
        const Detector = (window as any).BarcodeDetector as BarcodeDetectorCtor | undefined
        if (video && Detector) {
          try {
            const codes = await new Detector({ formats: ['qr_code'] }).detect(video)
            const value = codes?.[0]?.rawValue
            if (value) { await lookup(value); return }
          } catch {
            /* a decode hiccup is normal — keep the preview running */
          }
        }
        rafRef.current = requestAnimationFrame(() => { void tick() })
      }
      rafRef.current = requestAnimationFrame(() => { void tick() })
    } catch {
      setScanErr('Camera not available — type the order code below instead.')
      setCameraOn(false)
    }
  }

  const downloadScanner = () => {
    const origin = window.location.origin
    const html = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DETOMSITE — Order Scanner</title>
<style>body{font-family:system-ui;margin:2rem;max-width:30rem}
input{font-size:1.1rem;padding:.6rem;width:100%;box-sizing:border-box}
button{font-size:1rem;padding:.7rem 1rem;width:100%;margin-top:.6rem}
a.btn{display:block;text-align:center;text-decoration:none;padding:.8rem;background:#0f766e;color:#fff;border-radius:.5rem;margin-top:1rem}</style>
</head><body>
<h1>DETOMSITE — Order Scanner</h1>
<p>Type the order id printed under the student's QR, then open the shopkeeper app.</p>
<input id="code" placeholder="order id" autocomplete="off">
<button onclick="go()">Open in shopkeeper app</button>
<a class="btn" href="${origin}/scan">Camera scanner</a>
<script>function go(){var c=document.getElementById('code').value.trim();
if(!c)return;window.open('${origin}/scan?code='+encodeURIComponent(c),'_blank');}</script>
</body></html>`
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'detomsite-order-scanner.html'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }


  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="mx-auto max-w-md">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900">Scan an order</h1>
          <Link to="/mobile" className="text-sm font-semibold text-primary">← Back</Link>
        </div>

        <div className="overflow-hidden rounded-lg border-2 border-gray-200 bg-gray-900">
          <video ref={videoRef} playsInline muted className={cameraOn ? 'h-64 w-full object-cover' : 'hidden'} />
          {!cameraOn && (
            <div className="flex h-40 items-center justify-center text-sm text-gray-300">
              Camera is off
            </div>
          )}
        </div>

        <div className="mt-3 flex gap-2">
          {!cameraOn ? (
            <button onClick={() => void startCamera()} className="flex-1 rounded-btn bg-primary py-3 text-sm font-bold text-white">Start camera</button>
          ) : (
            <button onClick={stopCamera} className="flex-1 rounded-btn border border-gray-300 py-3 text-sm font-bold">Stop camera</button>
          )}
          <button onClick={downloadScanner} className="rounded-btn border-2 border-primary px-4 py-3 text-sm font-bold text-primary">Download scanner</button>
        </div>

        <div className="mt-4">
          <label className="mb-1 block text-sm font-bold text-gray-600">Or type the order code</label>
          <input
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void lookup(manual) }}
            placeholder={SCAN_PLACEHOLDER}
            className="w-full rounded-btn border-2 border-gray-200 px-4 py-2.5 text-sm outline-none focus:border-primary"
          />
          <button onClick={() => void lookup(manual)} className="mt-2 w-full rounded-btn bg-primary py-3 text-sm font-bold text-white">Find order</button>
        </div>

        {scanMsg && <p className="mt-3 text-sm font-semibold text-primary">{scanMsg}</p>}
        {scanErr && <p className="mt-3 text-sm font-semibold text-red-600">{scanErr}</p>}
      </div>
    </div>
  )
}


import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // updateViaCache: 'none' — always re-check the SW file so a stale cached
    // worker can never linger and block the newest one.
    navigator.serviceWorker.register('/mobile/sw.js', { updateViaCache: 'none' }).catch((err) => {
      // Visible in the browser console (F12) — helps diagnose why push is off.
      console.warn('Vendor app service worker registration failed:', err)
    })
  })
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

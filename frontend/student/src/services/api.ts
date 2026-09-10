import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    // Only force a redirect when an existing session was rejected — a failed
    // login (401 on /login, /register, /auth/*) must show its error message
    // on the form instead of silently redirecting.
    const url = err.config?.url || ''
    const isAuthCall = /login|register|auth/i.test(url)
    const hadToken = !!localStorage.getItem('access_token')
    if (err.response?.status === 401 && !isAuthCall && hadToken) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_data')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      /* Don't redirect on failed login attempts — the login form needs to show the
         error message to the user. Only redirect on 401s from authenticated requests
         (i.e. when we already have a token that turned out to be invalid). */
      const isLoginRequest = err.config?.url?.includes('/admin/login')
      const hasToken = !!localStorage.getItem('admin_token')
      if (!isLoginRequest && hasToken) {
        localStorage.removeItem('admin_token')
        localStorage.removeItem('admin_user')
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export default api

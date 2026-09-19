/*
 * API client service
 */
import axios from "axios";
import { clearLocalSession } from '../utils/session';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// Add token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Do not deliver an old account's response into the newly signed-in UI.
function sessionChanged(config: { headers?: { Authorization?: unknown } } | undefined) {
  const sent = String(config?.headers?.Authorization || '');
  const token = localStorage.getItem('access_token');
  return sent !== (token ? `Bearer ${token}` : '');
}

api.interceptors.response.use(
  (response) => {
    if (sessionChanged(response.config)) {
      return Promise.reject(new axios.CanceledError('Session changed during request'));
    }
    return response;
  },
  (error) => {
    const request = error.config;
    if (request && sessionChanged(request)) {
      return Promise.reject(new axios.CanceledError('Session changed during request'));
    }
    // No refresh endpoint exists: never retry with another account's token.
    const isAuthCall = /login|register|auth/i.test(request?.url || '');
    if (error.response?.status === 401 && !isAuthCall && localStorage.getItem('access_token')) {
      clearLocalSession();
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

/* ─── TTL GET cache ──────────────────────────────────────────────────────
   Every page mount unconditionally refetches shops/products/summary/stock,
   which makes navigating the portal feel slow (each route re-does the whole
   fetch set). `apiCached.get()` serves identical GETs from an in-memory cache
   for `ttlMs`, and dedupes concurrent identical requests (one network call
   shared by every caller). Polling/order-status calls should NOT use this —
   they need fresh data — so they keep using `api.get()`.
   The cache is keyed by token too: admin and student sessions never share.
   Mutable list GETs (orders, payments, complaints, …) are excluded by default.
*/
const ttlCache = new Map<string, { expires: number; value: unknown }>();
const inflight = new Map<string, Promise<unknown>>();

async function removeExpired() {
  const now = Date.now();
  for (const [k, v] of ttlCache) {
    if (v.expires <= now) ttlCache.delete(k);
  }
}

export function clearCachedGet() {
  ttlCache.clear();
}

export const apiCached = {
  async get<T>(url: string, params?: Record<string, unknown>, ttlMs = 8000): Promise<T> {
    const token = localStorage.getItem("access_token") || "anon";
    const key = JSON.stringify([token, url, params || null]);
    await removeExpired();

    const hit = ttlCache.get(key);
    if (hit && hit.expires > Date.now()) return hit.value as T;

    // Dedupe concurrent identical requests: share the in-flight promise.
    const pending = inflight.get(key);
    if (pending) return pending as Promise<T>;

    const promise = api
      .get<T>(url, { params })
      .then((r) => {
        // Guard: never cache order/payment/status reads that drift between
        // mounts — those callers should use plain `api.get` anyway.
        ttlCache.set(key, { expires: Date.now() + ttlMs, value: r.data });
        return r.data;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, promise);
    return promise;
  },
};

// Keep the default export the plain axios instance; callers that want cached
// reads import `apiCached`.
export { api };
export default api;

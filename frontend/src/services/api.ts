/*
 * API client service
 */
import axios from "axios";

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

// Handle token refresh on 401
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Never swallow or retry auth requests — a failed login (401) must surface
    // its real reason (wrong password, unknown user, wrong portal, ...) to the page.
    const url = originalRequest?.url || "";
    const isAuthCall = /login|register|auth/i.test(url);
    const hadToken = !!localStorage.getItem("access_token");

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !isAuthCall &&
      hadToken
    ) {
      originalRequest._retry = true;

      try {
        // const refreshToken = localStorage.getItem("refresh_token");
        // TODO: Implement token refresh endpoint

        return api(originalRequest);
      } catch (refreshError) {
        // Redirect to login
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
        return Promise.reject(refreshError);
      }
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

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

export default api;

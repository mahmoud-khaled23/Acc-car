// API client — Axios instance + typed helpers for Accident-Intel.
//
// Mock mode is controlled by VITE_MOCK_MODE (the documented flag); the older
// VITE_USE_MOCK name is still honoured so existing .env files keep working.
// When mock mode is off, requests go to VITE_API_BASE_URL — by default the
// empty string, which means "same origin", i.e. the Vite dev-server proxy
// (see vite.config.ts) forwards /api requests to the FastAPI backend.

import axios, {
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';

// ---------------------------------------------------------------------------
// Environment flags
// ---------------------------------------------------------------------------

const env = import.meta.env as Record<string, string | undefined>;

export const isMockMode: boolean =
  String(env.VITE_MOCK_MODE ?? env.VITE_USE_MOCK ?? 'false').toLowerCase() === 'true';

// Empty default = same-origin (Vite proxy in dev, same host behind a reverse proxy).
const BASE_URL: string = (env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

/** Error carrying the HTTP status so callers can tell 404 from real failures. */
export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

const client: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  // Video analysis and damage estimation run synchronously inside the request
  // for the direct endpoints, so allow generous timeouts.
  timeout: 120_000,
});

// Request interceptor — attach Content-Type for JSON payloads
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig): InternalAxiosRequestConfig => {
    if (!config.headers['Content-Type']) {
      config.headers['Content-Type'] = 'application/json';
    }
    return config;
  },
  (error: unknown) => Promise.reject(error),
);

// Response interceptor — normalize errors into ApiError
client.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status;
      const detail = (error.response?.data as { detail?: unknown })?.detail;
      const message =
        (typeof detail === 'string' ? detail : undefined) ??
        error.message ??
        'An unknown API error occurred';
      return Promise.reject(new ApiError(message, status));
    }
    return Promise.reject(error);
  },
);

// ---------------------------------------------------------------------------
// Typed helper wrappers
// ---------------------------------------------------------------------------

/** GET request — returns unwrapped response data */
export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await client.get<T>(url, { params });
  return response.data;
}

/** GET that turns a 404 into null (sub-resources that are not ready yet). */
export async function getOrNull<T>(url: string, params?: Record<string, unknown>): Promise<T | null> {
  try {
    return await get<T>(url, params);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** POST request with a JSON body — returns unwrapped response data */
export async function post<T>(url: string, body?: unknown): Promise<T> {
  const response = await client.post<T>(url, body);
  return response.data;
}

/** POST request with a FormData (multipart) body — returns unwrapped response data */
export async function postForm<T>(url: string, formData: FormData): Promise<T> {
  const response = await client.post<T>(url, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

/** DELETE request */
export async function del<T>(url: string): Promise<T> {
  const response = await client.delete<T>(url);
  return response.data;
}

/** Artificial latency helper for realistic mock responses (ms) */
export function mockDelay(ms: number = 600): Promise<void> {
  const jitter = Math.floor(Math.random() * 200);
  return new Promise((resolve) => setTimeout(resolve, ms + jitter));
}

export default client;

import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// A pluggable token provider. AuthContext registers a Cognito ID-token getter
// (via Amplify) in prod mode. In demo mode this stays null and no Authorization
// header is sent — the backend (AUTH_MODE=dev) ignores auth headers entirely.
type TokenProvider = () => Promise<string | null>;
let tokenProvider: TokenProvider | null = null;

export function setTokenProvider(provider: TokenProvider | null): void {
  tokenProvider = provider;
}

// ── Active membership (role/tenant switching) ────────────────────────────────
// A user may hold several (role, tenant) memberships derived from their AD
// groups. The chosen one is persisted here and sent as headers on every
// request; the backend validates it against the user's memberships each time
// — selecting is possible, elevating is not.
const ACTIVE_ROLE_KEY = 'mlplatform.activeRole';
const ACTIVE_TENANT_KEY = 'mlplatform.activeTenant';

export interface ActiveMembership {
  role: string;
  tenantId: string | null;
}

export function getActiveMembership(): ActiveMembership | null {
  const role = localStorage.getItem(ACTIVE_ROLE_KEY);
  if (!role) return null;
  return { role, tenantId: localStorage.getItem(ACTIVE_TENANT_KEY) || null };
}

export function setActiveMembership(selection: ActiveMembership | null): void {
  if (!selection) {
    localStorage.removeItem(ACTIVE_ROLE_KEY);
    localStorage.removeItem(ACTIVE_TENANT_KEY);
    return;
  }
  localStorage.setItem(ACTIVE_ROLE_KEY, selection.role);
  if (selection.tenantId) {
    localStorage.setItem(ACTIVE_TENANT_KEY, selection.tenantId);
  } else {
    localStorage.removeItem(ACTIVE_TENANT_KEY);
  }
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const headers = AxiosHeaders.from(config.headers);
  const active = getActiveMembership();
  if (active) {
    headers.set('X-Active-Role', active.role);
    if (active.tenantId) headers.set('X-Active-Tenant', active.tenantId);
  }
  config.headers = headers;
  if (tokenProvider) {
    try {
      const token = await tokenProvider();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
    } catch {
      // If token acquisition fails we still send the request; the backend will
      // respond 401 and the UI reacts. Never crash the request pipeline here.
    }
  }
  return config;
});

// ── Retry logic: exponential backoff, up to 2 retries, only on network
// errors or 5xx responses. 4xx errors are returned immediately. ─────────────
const MAX_RETRIES = 2;

interface RetryConfig extends AxiosRequestConfig {
  _retryCount?: number;
}

function isRetryable(error: AxiosError): boolean {
  // No response => network/transient error.
  if (!error.response) return true;
  const status = error.response.status;
  return status >= 500 && status < 600;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined;
    if (!config || !isRetryable(error)) {
      return Promise.reject(error);
    }
    config._retryCount = config._retryCount ?? 0;
    if (config._retryCount >= MAX_RETRIES) {
      return Promise.reject(error);
    }
    config._retryCount += 1;
    const delay = 2 ** (config._retryCount - 1) * 400; // 400ms, 800ms
    await new Promise((resolve) => setTimeout(resolve, delay));
    return apiClient(config);
  },
);

export function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
    if (error.response?.status) {
      return `Request failed (${error.response.status}). ${error.message}`;
    }
    return error.message || 'Network error. Please try again.';
  }
  if (error instanceof Error) return error.message;
  return 'An unexpected error occurred.';
}

export { API_BASE_URL };

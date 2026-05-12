import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { attachParsedApiError } from './error';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Detect the canonical APIResponse envelope produced by the backend
 * (see api/v1/schemas/envelope.py). Every /api/* response is wrapped
 * by ``EnvelopeRoute`` into ``{code, message, data, timestamp}``.
 */
function isApiEnvelope(value: unknown): value is { code: number; message: string; data: unknown; timestamp: string } {
  return (
    typeof value === 'object'
    && value !== null
    && 'code' in value
    && 'message' in value
    && 'timestamp' in value
    && typeof (value as { code: unknown }).code === 'number'
  );
}

apiClient.interceptors.response.use(
  (response) => {
    // Auto-unwrap APIResponse envelope so existing callers can keep
    // accessing ``response.data`` as the raw payload. Non-envelope
    // responses (e.g. SSE / binary downloads) are left untouched.
    // Only auto-unwrap for 2xx + ``code === 0`` envelopes. Callers that
    // opt into accepting non-2xx via ``validateStatus`` (e.g. 409 duplicate
    // submission) keep the raw envelope so they can read structured error
    // fields out of ``response.data``.
    const body = response.data;
    if (
      response.status >= 200
      && response.status < 300
      && isApiEnvelope(body)
      && body.code === 0
    ) {
      response.data = body.data;
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      const path = window.location.pathname + window.location.search;
      if (!path.startsWith('/login')) {
        const redirect = encodeURIComponent(path);
        window.location.assign(`/login?redirect=${redirect}`);
      }
    }
    attachParsedApiError(error);
    return Promise.reject(error);
  }
);

export default apiClient;

/**
 * Typed API client. Session lives in an httpOnly cookie set by the backend,
 * so every call sends credentials explicitly and 401s bubble up as a typed
 * error the UI can react to (spec #21: tokens never touch JS storage).
 */
export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(status: number, message: string, payload?: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers:
      init.body instanceof FormData
        ? (init.headers as HeadersInit)
        : { 'Content-Type': 'application/json', ...(init.headers as HeadersInit) },
    ...init,
  });

  const text = await res.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    let message = res.statusText;
    if (payload && typeof payload === 'object') {
      const p = payload as Record<string, unknown>;
      if (typeof p.detail === 'string') message = p.detail;
      else if (typeof p.message === 'string') {
        message = p.message;
        if (Array.isArray(p.errors)) message += `: ${(p.errors as string[]).join('; ')}`;
      } else if (Array.isArray(p.errors)) {
        message = (p.errors as string[]).join('; ');
      }
    }
    throw new ApiError(res.status, message || `Request failed (${res.status})`, payload);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

/** Suggested first questions the assistant can actually answer. */
export const ASSISTANT_SUGGESTIONS = [
  'What are the most important findings?',
  'Explain this dataset in simple language',
  'What is missing or inconsistent?',
  'Show potential rapid pass-through patterns',
  'Find transaction cycles',
  'Why was this record flagged?',
  'Compare successful and failed transactions',
  'Explain the most important model features',
];

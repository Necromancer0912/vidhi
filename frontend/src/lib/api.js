export const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized = null;

// AuthContext registers this so any request made with an expired token signs
// the user out once, instead of every caller handling 401 separately.
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

function detailFrom(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail[0]?.msg) {
    return data.detail[0].msg.replace(/^Value error,\s*/i, "");
  }
  return data.error || "";
}

async function send(path, { method = "GET", body, token, signal, keepalive = false } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers,
      signal,
      keepalive,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("network", 0);
  }

  if (res.status === 401 && token) onUnauthorized?.();
  return res;
}

export async function request(path, options) {
  const res = await send(path, options);
  let data = null;
  try {
    data = await res.json();
  } catch {}
  if (!res.ok) throw new ApiError(detailFrom(data), res.status);
  return data;
}

// Returns the raw Response so the caller can read the event stream.
export async function openChatStream(body, { token, signal }) {
  const res = await send("/chat", { method: "POST", body, token, signal });
  if (!res.ok) {
    let data = null;
    try {
      data = await res.json();
    } catch {}
    throw new ApiError(detailFrom(data), res.status);
  }
  return res;
}

// Maps an error to a sentence in the user's language. Server messages are
// English, so known cases are translated here and the rest fall back.
export function describeError(err, t) {
  if (!(err instanceof ApiError)) return t("errors.generic");
  const message = err.message || "";
  if (err.status === 0) return t("errors.network");
  if (err.status === 429) return /guest/i.test(message) ? t("errors.guestDaily") : t("errors.rateLimited");
  if (err.status === 403 && /deep search/i.test(message)) return t("errors.deepSearchAccount");
  if (err.status === 401) return t("errors.sessionExpired");
  if (err.status >= 500) return t("errors.server");
  return message || t("errors.generic");
}

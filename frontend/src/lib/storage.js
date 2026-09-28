// localStorage can throw (private mode, blocked storage) or hold stale JSON.
// Every read and write goes through here so neither can crash the app.

export function readJSON(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}

export function readString(key, fallback = null) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeString(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

export function remove(...keys) {
  try {
    keys.forEach((k) => localStorage.removeItem(k));
  } catch {}
}

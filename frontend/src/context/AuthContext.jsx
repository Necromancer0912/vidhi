import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { request, setUnauthorizedHandler } from "../lib/api";
import { readJSON, readString, remove, writeJSON, writeString } from "../lib/storage";

const AuthContext = createContext(null);

export const GUEST_ANSWER_LIMIT = 5;

// Reads `exp` without verifying the signature (the server does that); used only
// to drop a stored token that has already expired.
function tokenExpired(token) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return !payload.exp || payload.exp * 1000 <= Date.now();
  } catch {
    return true;
  }
}

function loadSession() {
  // Earlier versions stored these under other keys, and kept a guest cookie.
  const token = readString("vidhi_token");
  const user = readJSON("vidhi_user") || readJSON("vidhi_current_user");
  remove("vidhi_current_user", "vidhi_auth_mode", "vidhi_users", "vidhi_onboarded_guest");
  document.cookie = "vidhi_guest_usage=; Max-Age=0; path=/; SameSite=Lax";

  if (!token || !user?.email || tokenExpired(token)) {
    remove("vidhi_token", "vidhi_user");
    return { token: null, user: null };
  }
  return { token, user: { name: String(user.name || ""), email: String(user.email), tier: user.tier === "pro" ? "pro" : "free" } };
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(loadSession);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [guestUsed, setGuestUsed] = useState(() => {
    const saved = readJSON("vidhi_guest_usage");
    return Math.min(GUEST_ANSWER_LIMIT, Number(saved?.answerCount ?? saved?.used ?? 0) || 0);
  });

  useEffect(() => {
    if (session.token) {
      writeString("vidhi_token", session.token);
      writeJSON("vidhi_user", session.user);
    } else {
      remove("vidhi_token", "vidhi_user");
    }
  }, [session]);

  useEffect(() => writeJSON("vidhi_guest_usage", { used: guestUsed }), [guestUsed]);

  const signOut = useCallback(() => setSession({ token: null, user: null }), []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setSession((s) => {
        if (s.token) setSessionExpired(true);
        return { token: null, user: null };
      });
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const finish = (data) => {
    setSession({ token: data.token, user: data.user });
    setSessionExpired(false);
    return data.user;
  };

  // Each resolves with the user or throws: ApiError for HTTP/network
  // failures, Error(message) when the server declines (wrong password etc.).
  const authenticate = useCallback(async (path, body) => {
    const data = await request(path, { method: "POST", body });
    if (!data?.success) throw new Error(data?.error || "");
    return finish(data);
  }, []);

  const signIn = useCallback((email, password) => authenticate("/auth/login", { email, password }), [authenticate]);
  const signUp = useCallback((name, email, password) => authenticate("/auth/signup", { name, email, password }), [authenticate]);
  const signInWithGoogle = useCallback((accessToken) => authenticate("/auth/google", { access_token: accessToken }), [authenticate]);

  const recordGuestAnswer = useCallback(() => setGuestUsed((n) => Math.min(GUEST_ANSWER_LIMIT, n + 1)), []);

  const value = useMemo(
    () => ({
      token: session.token,
      user: session.user,
      isGuest: !session.token,
      guestUsed,
      guestRemaining: GUEST_ANSWER_LIMIT - guestUsed,
      guestLimitReached: !session.token && guestUsed >= GUEST_ANSWER_LIMIT,
      sessionExpired,
      dismissSessionExpired: () => setSessionExpired(false),
      signIn,
      signUp,
      signInWithGoogle,
      signOut,
      recordGuestAnswer,
    }),
    [session, guestUsed, sessionExpired, signIn, signUp, signInWithGoogle, signOut, recordGuestAnswer]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

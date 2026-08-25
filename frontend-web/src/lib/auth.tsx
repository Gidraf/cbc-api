/**
 * Authentication state.
 *
 * Storage keys match the legacy console (`cbc_token`, `cbc_role`, …) so a user
 * signed into one is signed into the other during the migration.
 */
import React from "react";
import { AUTH_EXPIRED_EVENT, fetchJson } from "../api";

export type Role = "admin" | "operator" | "reviewer" | "developer";

const KEYS = {
  token: "cbc_token",
  role: "cbc_role",
  username: "cbc_username",
  subject: "cbc_subject",
} as const;

/** Rights by role, mirroring the backend's require_roles decorators. */
const RIGHTS: Record<Role, string[]> = {
  admin: ["generate", "review", "approve", "publish", "configure", "read"],
  operator: ["generate", "review", "read"],
  reviewer: ["review", "approve", "read"],
  developer: ["read"],
};

export type AuthState = {
  token: string;
  role: Role | null;
  username: string;
  ready: boolean;
};

type AuthContextValue = AuthState & {
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
  can: (right: string) => boolean;
  expiredReason: string | null;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

function decodeExpiry(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1] || ""));
    return typeof payload?.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

export function isTokenValid(token: string): boolean {
  if (!token) return false;
  const exp = decodeExpiry(token);
  // A token with no expiry claim is treated as valid; the API is the authority.
  return exp === null ? true : exp * 1000 > Date.now();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState>(() => {
    const token = localStorage.getItem(KEYS.token) || "";
    if (!isTokenValid(token)) {
      Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
      return { token: "", role: null, username: "", ready: true };
    }
    return {
      token,
      role: (localStorage.getItem(KEYS.role) as Role) || null,
      username: localStorage.getItem(KEYS.username) || "",
      ready: true,
    };
  });
  const [expiredReason, setExpiredReason] = React.useState<string | null>(null);

  const signOut = React.useCallback(() => {
    Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
    setState({ token: "", role: null, username: "", ready: true });
  }, []);

  // The API client dispatches this on any 401, so one expired call signs the
  // whole console out rather than leaving half the screens silently empty.
  React.useEffect(() => {
    const onExpired = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setExpiredReason(detail?.reason || "Your session expired. Please sign in again.");
      signOut();
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [signOut]);

  // Sign out a moment before the token actually expires, so a long-running
  // generation does not fail halfway through with an opaque error.
  React.useEffect(() => {
    if (!state.token) return;
    const exp = decodeExpiry(state.token);
    if (!exp) return;
    const ms = exp * 1000 - Date.now() - 30_000;
    if (ms <= 0) {
      signOut();
      return;
    }
    const timer = setTimeout(() => {
      setExpiredReason("Your session expired. Please sign in again.");
      signOut();
    }, Math.min(ms, 2 ** 31 - 1));
    return () => clearTimeout(timer);
  }, [state.token, signOut]);

  const signIn = React.useCallback(async (username: string, password: string) => {
    const res = await fetchJson<any>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    const token = res.access_token || res.token || "";
    const role = (res.role as Role) || "operator";
    if (!token) throw new Error("Sign-in succeeded but no token was returned.");

    localStorage.setItem(KEYS.token, token);
    localStorage.setItem(KEYS.role, role);
    localStorage.setItem(KEYS.username, username);
    localStorage.setItem(KEYS.subject, res.subject || username);

    setExpiredReason(null);
    setState({ token, role, username, ready: true });
  }, []);

  const can = React.useCallback(
    (right: string) => (state.role ? RIGHTS[state.role]?.includes(right) ?? false : false),
    [state.role]
  );

  const value = React.useMemo(
    () => ({ ...state, signIn, signOut, can, expiredReason }),
    [state, signIn, signOut, can, expiredReason]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

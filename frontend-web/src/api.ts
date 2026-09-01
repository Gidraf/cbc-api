export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";

/**
 * The full URL for an API path.
 *
 * `VITE_API_BASE_URL` is an ORIGIN, not a mount point. It exists for the case
 * where the console is served from somewhere other than the API: set it to
 * https://api.example.com and every path works.
 *
 * It is NOT a prefix to put in front of every route, because this API does not
 * live under one. The versioned routes are /api/v1/..., but /admin, /generate,
 * /pipeline and /health are served at the ROOT. Setting it to "/api" turned
 * /admin/pipeline-bindings into /api/admin/pipeline-bindings — a 404 the
 * console showed as an empty Model-per-station screen with no error, because a
 * 404 on a list endpoint looks exactly like an empty list.
 *
 * So a same-origin base contributes nothing: the dev/preview proxy already
 * forwards /api, /admin, /generate, /pipeline and /health to the API without
 * rewriting them, which means the path the console asks for is the path the
 * API must see. Only an absolute base is prepended.
 */
export function apiUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  if (!/^https?:\/\//i.test(API_BASE_URL)) return cleanPath;
  const base = API_BASE_URL;
  // A base that already ends in /api plus a path that starts with it is the
  // /api/api that this guard has always existed to prevent.
  if (base.endsWith("/api") && cleanPath.startsWith("/api/")) {
    return `${base.slice(0, -4)}${cleanPath}`;
  }
  return `${base}${cleanPath}`;
}

export const AUTH_EXPIRED_EVENT = "cbc:auth_expired";

export type AuthHeaders = {
  bearerToken?: string;
  apiKey?: string;
};

export function triggerAuthExpired(reason: string = "Session expired. Please sign in again.") {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { reason } }));
  }
}

/** A binary download, with the same base-URL and auth handling as fetchJson.
 *
 *  fetchJson reads the response as text and parses it, which turns a zip into
 *  mojibake. And a plain <a href> cannot be used instead: it carries no
 *  Authorization header, so the browser would download the sign-in page. */
export async function fetchBlob(
  path: string,
  auth?: AuthHeaders
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers();
  if (auth?.bearerToken) headers.set("Authorization", `Bearer ${auth.bearerToken}`);
  if (auth?.apiKey) headers.set("x-api-key", auth.apiKey);

  const response = await fetch(apiUrl(path), { headers });
  if (!response.ok) {
    // The error body is JSON even when the success body is not.
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body?.error?.message || body?.detail || detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new Error(detail);
  }

  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] || "download" };
}

export async function fetchJson<T>(path: string, init?: RequestInit, auth?: AuthHeaders): Promise<T> {
  const headers = new Headers(init?.headers || {});
  // A multipart upload must not carry a content-type we invented: only the
  // browser knows the boundary it generated, and setting the header here makes
  // the server unable to parse the parts.
  const isMultipart = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!headers.has("content-type") && !isMultipart) {
    headers.set("content-type", "application/json");
  }
  if (auth?.bearerToken) {
    headers.set("Authorization", `Bearer ${auth.bearerToken}`);
  }
  if (auth?.apiKey) {
    headers.set("x-api-key", auth.apiKey);
  }

  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const url = apiUrl(cleanPath);

  const response = await fetch(url, {
    headers,
    ...init
  });

  const text = await response.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { error: "SERVER_ERROR", message: text || response.statusText, status_code: response.status };
  }

  if (response.status === 401) {
    // Only trigger if this is not the login endpoint itself
    if (!cleanPath.includes("/auth/login")) {
      const msg = (body && typeof body === "object") ? (body.message || body.detail || "Session expired") : "Session expired";
      triggerAuthExpired(msg);
    }
  }

  if (!response.ok) {
    const errMsg = (body && typeof body === "object") ? (body.message || body.detail || body.error || JSON.stringify(body)) : text;
    const err = new Error(errMsg || `HTTP ${response.status} ${response.statusText}`);
    (err as any).data = body;
    (err as any).status = response.status;
    throw err;
  }

  return body as T;
}

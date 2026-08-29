export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";

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

  let cleanPath = path.startsWith("/") ? path : `/${path}`;
  let baseUrl = API_BASE_URL;
  if (baseUrl.endsWith("/api") && cleanPath.startsWith("/api")) {
    cleanPath = cleanPath.slice(4);
  }

  const response = await fetch(baseUrl ? `${baseUrl}${cleanPath}` : cleanPath, { headers });
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

  // Normalize path and base URL to prevent duplicate /api/api
  let cleanPath = path.startsWith("/") ? path : `/${path}`;
  let baseUrl = API_BASE_URL;
  if (baseUrl.endsWith("/api") && cleanPath.startsWith("/api")) {
    cleanPath = cleanPath.slice(4);
  }

  const url = baseUrl ? `${baseUrl}${cleanPath}` : cleanPath;

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

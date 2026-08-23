export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";

export type AuthHeaders = {
  bearerToken?: string;
  apiKey?: string;
};

export async function fetchJson<T>(path: string, init?: RequestInit, auth?: AuthHeaders): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("content-type")) {
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

  if (!response.ok) {
    const errMsg = (body && typeof body === "object") ? (body.message || body.detail || body.error || JSON.stringify(body)) : text;
    const err = new Error(errMsg || `HTTP ${response.status} ${response.statusText}`);
    (err as any).data = body;
    (err as any).status = response.status;
    throw err;
  }

  return body as T;
}

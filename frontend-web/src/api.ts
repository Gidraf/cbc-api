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
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new Error(JSON.stringify(body ?? { status: response.status, message: response.statusText }, null, 2));
  }

  return body as T;
}

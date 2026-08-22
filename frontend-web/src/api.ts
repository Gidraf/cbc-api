export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

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

  const response = await fetch(`${API_BASE_URL}${path}`, {
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

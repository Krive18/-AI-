import type { ApiErrorPayload } from "@/types/api";

export type Portal = "operator" | "admin";

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly requestId: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const csrfTokens: Record<Portal, string | null> = {
  operator: null,
  admin: null,
};

export function setCsrfToken(
  value: string | null,
  portal: Portal = "operator",
) {
  csrfTokens[portal] = value;
}

export function resolvePortal(path: string, explicit?: Portal): Portal {
  if (explicit) return explicit;
  if (path.startsWith("/api/v1/admin")) return "admin";
  if (
    typeof window !== "undefined" &&
    window.location.pathname.startsWith("/admin")
  )
    return "admin";
  return "operator";
}

async function apiError(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // The stable fallback below prevents transport internals leaking into UI.
  }
  return new ApiError(
    payload?.error.code ?? "REQUEST_FAILED",
    payload?.error.message ?? "请求未完成，请稍后重试",
    payload?.error.requestId ?? response.headers.get("X-Request-Id") ?? "",
    response.status,
  );
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { portal?: Portal } = {},
): Promise<T> {
  const { portal: requestedPortal, ...requestInit } = init;
  const portal = resolvePortal(path, requestedPortal);
  const headers = new Headers(requestInit.headers);
  headers.set("X-Portal", portal);
  if (
    requestInit.body &&
    !(requestInit.body instanceof FormData) &&
    !headers.has("Content-Type")
  )
    headers.set("Content-Type", "application/json");
  const method = (requestInit.method ?? "GET").toUpperCase();
  const csrfToken = csrfTokens[portal];
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, {
    ...requestInit,
    headers,
    credentials: "include",
  });
  if (!response.ok) throw await apiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiDownload(
  path: string,
  portal?: Portal,
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "X-Portal": resolvePortal(path, portal) },
  });
  if (!response.ok) throw await apiError(response);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  let filename: string | null;
  try {
    filename = encoded ? decodeURIComponent(encoded) : (plain ?? null);
  } catch {
    filename = null;
  }
  return { blob: await response.blob(), filename };
}

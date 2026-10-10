import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiDownload, apiFetch, setCsrfToken } from "@/services/http";

afterEach(() => {
  setCsrfToken(null);
  setCsrfToken(null, "admin");
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends JSON requests with credentials and the CSRF token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ accepted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("csrf-test-token");

    await expect(
      apiFetch<{ accepted: boolean }>("/api/v1/example", {
        method: "POST",
        body: JSON.stringify({ name: "sample" }),
      }),
    ).resolves.toEqual({ accepted: true });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(path).toBe("/api/v1/example");
    expect(init.credentials).toBe("include");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test-token");
    expect(headers.get("X-Portal")).toBe("operator");
  });

  it("uses the admin portal token and header for admin API paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ accepted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("operator-token");
    setCsrfToken("admin-token", "admin");

    await apiFetch("/api/v1/admin/example", {
      method: "POST",
      body: JSON.stringify({ name: "sample" }),
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get("X-Portal")).toBe("admin");
    expect(headers.get("X-CSRF-Token")).toBe("admin-token");
  });

  it("prefers an explicit portal over path and location", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ accepted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("admin-token", "admin");

    await apiFetch("/api/v1/auth/me", { portal: "admin" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Headers).get("X-Portal")).toBe("admin");
  });

  it("maps stable API errors without exposing transport details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "FORBIDDEN",
              message: "没有操作权限",
              requestId: "request-123",
            },
          }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const error = await apiFetch("/api/v1/admin/example").catch(
      (reason: unknown) => reason,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      name: "ApiError",
      code: "FORBIDDEN",
      message: "没有操作权限",
      requestId: "request-123",
      status: 403,
    });
  });
});

describe("apiDownload", () => {
  it("decodes UTF-8 attachment filenames", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("1\n00:00:00,000 --> 00:00:01,000\n你好\n", {
          status: 200,
          headers: {
            "Content-Disposition":
              "attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.srt",
          },
        }),
      ),
    );

    const result = await apiDownload("/api/v1/download/subtitle");

    expect(result.filename).toBe("中文.srt");
    expect(await result.blob.text()).toContain("你好");
  });
});

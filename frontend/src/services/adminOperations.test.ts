import { afterEach, describe, expect, it, vi } from "vitest";

import {
  downloadAdminImageGeneration,
  listAdminImageGenerations,
} from "@/services/adminOperations";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listAdminImageGenerations", () => {
  it("requests the admin image generation list with pagination params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listAdminImageGenerations(20, 40)).resolves.toEqual({
      items: [],
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/admin/image-generations?limit=20&offset=40");
    expect(init.credentials).toBe("include");
    expect((init.headers as Headers).get("X-Portal")).toBe("admin");
  });
});

describe("downloadAdminImageGeneration", () => {
  it("requests the admin image download endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("png-bytes", {
        status: 200,
        headers: {
          "Content-Disposition": "attachment; filename*=UTF-8''job-1.png",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await downloadAdminImageGeneration(
      "01M1GTESTIMAGEJOB0000000000",
      1,
    );

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/admin/image-generations/01M1GTESTIMAGEJOB0000000000/images/1",
    );
    expect(result.filename).toBe("job-1.png");
    expect(await result.blob.text()).toBe("png-bytes");
  });
});

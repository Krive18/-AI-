// @vitest-environment jsdom

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/services/http";
import type { Account } from "@/types/api";

import { useAuthStore } from "./auth";

vi.mock("@/services/http", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/http")>();
  return { ...original, apiFetch: vi.fn() };
});

const baseAccount: Account = {
  publicId: "01JTESTACCOUNT0000000000001",
  loginName: "ceshi",
  displayName: "测试账号",
  role: 1,
  status: 1,
  mustChangePassword: false,
  videogenEnabled: true,
};

describe("useAuthStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiFetch).mockReset();
  });

  it("initialize 映射账号的 videogenEnabled 字段", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      account: baseAccount,
      csrfToken: "csrf",
    });
    const store = useAuthStore();

    await store.initialize("operator");

    expect(store.account?.videogenEnabled).toBe(true);
  });

  it("initialize 保留未授权账号的 videogenEnabled=false", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      account: { ...baseAccount, videogenEnabled: false },
      csrfToken: "csrf",
    });
    const store = useAuthStore();

    await store.initialize("operator");

    expect(store.account?.videogenEnabled).toBe(false);
  });
});

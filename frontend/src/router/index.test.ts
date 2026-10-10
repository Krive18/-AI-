// @vitest-environment jsdom

import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { installAuthGuard, routes } from "@/router";

type Session = {
  mustChangePassword: boolean;
  videogenEnabled?: boolean;
} | null;

const testState = vi.hoisted(() => ({
  initialize: vi.fn(),
  auth: {
    activePortal: "operator" as "operator" | "admin",
    accounts: {
      operator: null as Session,
      admin: null as Session,
    },
    setActivePortal(portal: "operator" | "admin") {
      testState.auth.activePortal = portal;
    },
  },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    accounts: testState.auth.accounts,
    initialize: testState.initialize,
    setActivePortal: testState.auth.setActivePortal,
  }),
}));

async function createTestRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes,
  });
  installAuthGuard(router);
  await router.push("/");
  return router;
}

describe("authGuard", () => {
  beforeEach(() => {
    testState.initialize.mockReset().mockResolvedValue(undefined);
    testState.auth.activePortal = "operator";
    testState.auth.accounts.operator = null;
    testState.auth.accounts.admin = null;
  });

  it("未登录访问管理端页面时跳到管理后台登录页并携带 redirect", async () => {
    const router = await createTestRouter();

    await router.push("/admin/accounts");

    expect(router.currentRoute.value.name).toBe("admin-login");
    expect(router.currentRoute.value.query.redirect).toBe("/admin/accounts");
  });

  it("未登录访问运营端页面时跳到工作台登录页并携带 redirect", async () => {
    const router = await createTestRouter();

    await router.push("/translations");

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/translations");
  });

  it("只有管理端会话时访问运营页面会跳到工作台登录页", async () => {
    testState.auth.accounts.admin = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/translations/new");

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/translations/new");
  });

  it("已登录管理员访问管理后台登录页时跳回 /admin", async () => {
    testState.auth.accounts.admin = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/admin/login");

    expect(router.currentRoute.value.path).toBe("/admin");
  });

  it("已登录运营成员访问工作台登录页时跳回 /translations/new", async () => {
    testState.auth.accounts.operator = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/login");

    expect(router.currentRoute.value.path).toBe("/translations/new");
  });

  it("只有管理端会话时访问工作台登录页停留在登录页", async () => {
    testState.auth.accounts.admin = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/login");

    expect(router.currentRoute.value.name).toBe("login");
  });

  it("只有运营端会话时访问管理后台登录页停留在登录页", async () => {
    testState.auth.accounts.operator = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/admin/login");

    expect(router.currentRoute.value.name).toBe("admin-login");
  });

  it("只有运营端会话时访问管理端页面会跳到管理后台登录页", async () => {
    testState.auth.accounts.operator = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/admin/accounts");

    expect(router.currentRoute.value.name).toBe("admin-login");
    expect(router.currentRoute.value.query.redirect).toBe("/admin/accounts");
  });

  it("已登录运营成员可以正常访问运营页面", async () => {
    testState.auth.accounts.operator = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/translations/new");

    expect(router.currentRoute.value.name).toBe("translation-new");
  });

  it("未开通图生视频的运营成员访问 /videogen 时跳回新建翻译页", async () => {
    testState.auth.accounts.operator = {
      mustChangePassword: false,
      videogenEnabled: false,
    };
    const router = await createTestRouter();

    await router.push("/videogen");

    expect(router.currentRoute.value.path).toBe("/translations/new");
  });

  it("账号缺少图生视频字段时访问 /videogen 同样被拦截", async () => {
    testState.auth.accounts.operator = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/videogen");

    expect(router.currentRoute.value.path).toBe("/translations/new");
  });

  it("已开通图生视频的运营成员可以正常访问 /videogen", async () => {
    testState.auth.accounts.operator = {
      mustChangePassword: false,
      videogenEnabled: true,
    };
    const router = await createTestRouter();

    await router.push("/videogen");

    expect(router.currentRoute.value.name).toBe("videogen");
  });

  it("运营端会话需要改密时跳改密页并携带 portal", async () => {
    testState.auth.accounts.operator = { mustChangePassword: true };
    const router = await createTestRouter();

    await router.push("/translations/new");

    expect(router.currentRoute.value.name).toBe("change-password");
    expect(router.currentRoute.value.query.portal).toBe("operator");
  });

  it("管理端会话需要改密时跳改密页并携带 portal=admin", async () => {
    testState.auth.accounts.admin = { mustChangePassword: true };
    const router = await createTestRouter();

    await router.push("/admin");

    expect(router.currentRoute.value.name).toBe("change-password");
    expect(router.currentRoute.value.query.portal).toBe("admin");
  });

  it("改密页按 query.portal 选择激活会话", async () => {
    testState.auth.accounts.operator = { mustChangePassword: true };
    testState.auth.accounts.admin = { mustChangePassword: true };
    const router = await createTestRouter();

    await router.push("/change-password?portal=admin");

    expect(router.currentRoute.value.name).toBe("change-password");
    expect(testState.auth.activePortal).toBe("admin");
  });

  it("改密页在没有会话时跳回工作台登录页", async () => {
    const router = await createTestRouter();

    await router.push("/change-password");

    expect(router.currentRoute.value.name).toBe("login");
  });

  it("改密页在会话无需改密时回对应首页", async () => {
    testState.auth.accounts.admin = { mustChangePassword: false };
    const router = await createTestRouter();

    await router.push("/change-password?portal=admin");

    expect(router.currentRoute.value.path).toBe("/admin");
  });
});

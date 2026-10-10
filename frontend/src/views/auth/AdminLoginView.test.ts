// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminLoginView from "./AdminLoginView.vue";

const testState = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
  route: { query: {} as Record<string, string> },
  auth: {
    account: null as null | { mustChangePassword: boolean },
    loading: false,
    error: "",
  },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    ...testState.auth,
    login: testState.login,
  }),
}));

vi.mock("vue-router", () => ({
  useRoute: () => testState.route,
  useRouter: () => ({ replace: testState.replace }),
}));

const RouterLinkStub = {
  props: ["to"],
  template: '<a :href="to"><slot /></a>',
};

function mountAdminLogin() {
  return mount(AdminLoginView, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  });
}

describe("AdminLoginView", () => {
  beforeEach(() => {
    testState.login.mockReset().mockResolvedValue(undefined);
    testState.replace.mockReset().mockResolvedValue(undefined);
    testState.route.query = {};
    testState.auth.account = null;
    testState.auth.loading = false;
    testState.auth.error = "";
  });

  it("渲染标题、副标题和运营工作台入口", () => {
    const wrapper = mountAdminLogin();

    expect(wrapper.text()).toContain("寰语管理后台");
    expect(wrapper.text()).toContain("内部管理系统，仅限管理员账号");
    const link = wrapper.get(".admin-login-card__footer a");
    expect(link.attributes("href")).toBe("/login");
    expect(link.text()).toContain("运营工作台登录");
  });

  it("管理员账号登录成功后跳转 /admin", async () => {
    testState.auth.account = { mustChangePassword: false };
    const wrapper = mountAdminLogin();

    await wrapper.get("#login-name").setValue("admin");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.login).toHaveBeenCalledWith("admin", "secret123", "admin");
    expect(testState.replace).toHaveBeenCalledWith("/admin");
  });

  it("携带 redirect 查询时优先跳回原目标", async () => {
    testState.auth.account = { mustChangePassword: false };
    testState.route.query = { redirect: "/admin/accounts" };
    const wrapper = mountAdminLogin();

    await wrapper.get("#login-name").setValue("admin");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.replace).toHaveBeenCalledWith("/admin/accounts");
  });

  it("需要改密时跳转到管理端入口的改密页", async () => {
    testState.auth.account = { mustChangePassword: true };
    const wrapper = mountAdminLogin();

    await wrapper.get("#login-name").setValue("admin");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.replace).toHaveBeenCalledWith(
      "/change-password?portal=admin",
    );
  });

  it("登录失败时就地展示 auth store 的错误", async () => {
    testState.login.mockRejectedValue(new Error("bad credentials"));
    testState.auth.error = "账号或密码错误";
    const wrapper = mountAdminLogin();

    await wrapper.get("#login-name").setValue("admin");
    await wrapper.get("#password").setValue("wrong");
    await wrapper.get("form").trigger("submit");
    await wrapper.vm.$nextTick();

    expect(wrapper.get("[role='alert']").text()).toContain("账号或密码错误");
    expect(testState.replace).not.toHaveBeenCalled();
  });
});

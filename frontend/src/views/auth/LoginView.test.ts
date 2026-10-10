// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginView from "./LoginView.vue";

const testState = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
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
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: testState.replace }),
}));

const RouterLinkStub = {
  props: ["to"],
  template: '<a :href="to"><slot /></a>',
};

function mountLogin() {
  return mount(LoginView, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  });
}

describe("LoginView", () => {
  beforeEach(() => {
    testState.login.mockReset().mockResolvedValue(undefined);
    testState.replace.mockReset().mockResolvedValue(undefined);
    testState.auth.account = null;
    testState.auth.loading = false;
    testState.auth.error = "";
    window.localStorage.clear();
  });

  it("使用账号和密码以运营入口调用真实 auth store", async () => {
    const wrapper = mountLogin();

    await wrapper.get("#login-name").setValue("  operator  ");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.login).toHaveBeenCalledWith(
      "operator",
      "secret123",
      "operator",
    );
    expect(wrapper.text()).not.toContain("邮箱");
  });

  it("支持显示和隐藏密码", async () => {
    const wrapper = mountLogin();
    const input = wrapper.get<HTMLInputElement>("#password");
    const toggle = wrapper.get("[data-testid='password-toggle']");

    expect(input.attributes("type")).toBe("password");
    expect(toggle.attributes("aria-pressed")).toBe("false");

    await toggle.trigger("click");

    expect(input.attributes("type")).toBe("text");
    expect(toggle.attributes("aria-pressed")).toBe("true");
  });

  it("只保存用户明确选择记住的账号名", async () => {
    const wrapper = mountLogin();

    await wrapper.get("#login-name").setValue("operator");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("#remember-login-name").setValue(true);
    await wrapper.get("form").trigger("submit");

    expect(window.localStorage.getItem("linguasphere.rememberedLoginName")).toBe(
      "operator",
    );
    expect(window.localStorage.getItem("password")).toBeNull();
  });

  it("运营账号登录成功后跳转到工作台", async () => {
    testState.auth.account = { mustChangePassword: false };
    const wrapper = mountLogin();

    await wrapper.get("#login-name").setValue("operator");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.replace).toHaveBeenCalledWith("/translations/new");
  });

  it("需要改密时跳转到运营入口的改密页", async () => {
    testState.auth.account = { mustChangePassword: true };
    const wrapper = mountLogin();

    await wrapper.get("#login-name").setValue("operator");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");

    expect(testState.replace).toHaveBeenCalledWith(
      "/change-password?portal=operator",
    );
  });

  it("登录失败时就地展示 auth store 的错误且不跳转", async () => {
    testState.login.mockRejectedValue(new Error("forbidden"));
    testState.auth.error = "该账号为管理员，请从管理后台入口登录";
    const wrapper = mountLogin();

    await wrapper.get("#login-name").setValue("admin");
    await wrapper.get("#password").setValue("secret123");
    await wrapper.get("form").trigger("submit");
    await wrapper.vm.$nextTick();

    expect(wrapper.get("[role='alert']").text()).toContain(
      "该账号为管理员，请从管理后台入口登录",
    );
    expect(testState.replace).not.toHaveBeenCalled();
  });

  it("卡片底部提供管理后台登录入口", () => {
    const wrapper = mountLogin();

    const link = wrapper.get(".login-card__footer a");
    expect(link.attributes("href")).toBe("/admin/login");
    expect(link.text()).toContain("管理后台登录");
  });
});

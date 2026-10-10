// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ForcePasswordView from "./ForcePasswordView.vue";

const testState = vi.hoisted(() => ({
  changePassword: vi.fn(),
  replace: vi.fn(),
  route: { query: {} as Record<string, string> },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ changePassword: testState.changePassword }),
}));

vi.mock("vue-router", () => ({
  useRoute: () => testState.route,
  useRouter: () => ({ replace: testState.replace }),
}));

describe("ForcePasswordView", () => {
  beforeEach(() => {
    testState.changePassword.mockReset().mockResolvedValue(undefined);
    testState.replace.mockReset().mockResolvedValue(undefined);
    testState.route.query = {};
  });

  it("接受任意六位新密码并默认走运营入口", async () => {
    const wrapper = mount(ForcePasswordView);

    await wrapper.get("#current-password").setValue("temporary-password");
    await wrapper.get("#new-password").setValue("123456");
    await wrapper.get("#confirm-password").setValue("123456");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(testState.changePassword).toHaveBeenCalledWith(
      "temporary-password",
      "123456",
      "operator",
    );
    expect(testState.replace).toHaveBeenCalledWith({
      path: "/login",
      query: { passwordChanged: "1" },
    });
  });

  it("portal=admin 时按管理端会话改密并回管理后台登录页", async () => {
    testState.route.query = { portal: "admin" };
    const wrapper = mount(ForcePasswordView);

    await wrapper.get("#current-password").setValue("temporary-password");
    await wrapper.get("#new-password").setValue("123456");
    await wrapper.get("#confirm-password").setValue("123456");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(testState.changePassword).toHaveBeenCalledWith(
      "temporary-password",
      "123456",
      "admin",
    );
    expect(testState.replace).toHaveBeenCalledWith({ path: "/admin/login" });
  });

  it("拒绝不足六位的新密码", async () => {
    const wrapper = mount(ForcePasswordView);

    await wrapper.get("#current-password").setValue("temporary-password");
    await wrapper.get("#new-password").setValue("12345");
    await wrapper.get("#confirm-password").setValue("12345");
    await wrapper.get("form").trigger("submit");

    expect(testState.changePassword).not.toHaveBeenCalled();
    expect(wrapper.get("[role='alert']").text()).toContain("至少 6 位");
  });
});

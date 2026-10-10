// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import OperatorLayout from "./OperatorLayout.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ meta: { title: "运营工作台" } }),
  useRouter: () => ({ replace: vi.fn() }),
}));

const authState = vi.hoisted(() => ({
  account: null as null | { videogenEnabled?: boolean; displayName?: string },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ account: authState.account, logout: vi.fn() }),
}));

function mountLayout() {
  return mount(OperatorLayout, {
    global: {
      plugins: [createPinia()],
      stubs: {
        AppHeader: true,
        RouterView: true,
        AppToast: true,
        AppSidebar: {
          props: ["items"],
          template:
            '<nav><span v-for="item in items" :key="item.to">{{ item.label }}</span></nav>',
        },
      },
    },
  });
}

describe("OperatorLayout", () => {
  it("账号已开通图生视频时菜单包含图生视频入口", () => {
    authState.account = { videogenEnabled: true, displayName: "测试" };

    const wrapper = mountLayout();

    expect(wrapper.text()).toContain("图生视频");
  });

  it("账号未开通图生视频时菜单隐藏图生视频入口", () => {
    authState.account = { videogenEnabled: false, displayName: "测试" };

    const wrapper = mountLayout();

    expect(wrapper.text()).not.toContain("图生视频");
    expect(wrapper.text()).toContain("新建翻译");
    expect(wrapper.text()).toContain("图片生成");
  });

  it("账号信息缺失图生视频字段时默认隐藏入口", () => {
    authState.account = { displayName: "测试" };

    const wrapper = mountLayout();

    expect(wrapper.text()).not.toContain("图生视频");
  });
});

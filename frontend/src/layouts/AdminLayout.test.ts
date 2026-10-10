// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import AdminLayout from "./AdminLayout.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ meta: { title: "运行概览" } }),
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ logout: vi.fn() }),
}));

describe("AdminLayout", () => {
  it("管理员导航不提供进入运营端入口", () => {
    const wrapper = mount(AdminLayout, {
      global: {
        plugins: [createPinia()],
        stubs: {
          AppHeader: true,
          RouterView: true,
          AppSidebar: {
            props: ["items"],
            template:
              '<nav><span v-for="item in items" :key="item.to">{{ item.label }}</span></nav>',
          },
        },
      },
    });

    expect(wrapper.text()).not.toContain("进入运营端");
    expect(wrapper.text()).toContain("账号管理");
  });
});

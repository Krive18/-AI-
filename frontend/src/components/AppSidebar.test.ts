// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it } from "vitest";
import { markRaw } from "vue";

import AppSidebar from "./AppSidebar.vue";

const EmptyView = { template: "<div />" };
const EmptyIcon = markRaw({ template: "<span />" });

async function mountAt(
  path: string,
  items: Array<{ to: string; label: string }>,
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/admin",
        component: EmptyView,
        children: [
          { path: "", component: EmptyView, meta: { navItem: "/admin" } },
          {
            path: "accounts",
            component: EmptyView,
            meta: { navItem: "/admin/accounts" },
          },
        ],
      },
      {
        path: "/translations",
        component: EmptyView,
        children: [
          {
            path: "",
            component: EmptyView,
            meta: { navItem: "/translations" },
          },
          {
            path: "new",
            component: EmptyView,
            meta: { navItem: "/translations/new" },
          },
        ],
      },
    ],
  });
  await router.push(path);
  await router.isReady();

  return mount(AppSidebar, {
    props: {
      open: false,
      section: "导航",
      items: items.map((item) => ({ ...item, icon: EmptyIcon })),
    },
    global: { plugins: [createPinia(), router] },
  });
}

describe("AppSidebar", () => {
  it("管理端子页面只激活一个导航项", async () => {
    const wrapper = await mountAt("/admin/accounts", [
      { to: "/admin", label: "运行概览" },
      { to: "/admin/accounts", label: "账号管理" },
    ]);

    expect(wrapper.findAll(".nav-link.router-link-active")).toHaveLength(1);
    expect(wrapper.get(".nav-link.router-link-active").text()).toContain(
      "账号管理",
    );
  });

  it("新建翻译页面不会同时激活翻译记录", async () => {
    const wrapper = await mountAt("/translations/new", [
      { to: "/translations/new", label: "新建翻译" },
      { to: "/translations", label: "翻译记录" },
    ]);

    expect(wrapper.findAll(".nav-link.router-link-active")).toHaveLength(1);
    expect(wrapper.get(".nav-link.router-link-active").text()).toContain(
      "新建翻译",
    );
  });
});

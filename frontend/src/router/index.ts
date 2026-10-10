import {
  createRouter,
  createWebHistory,
  type Router,
  type RouteLocationNormalized,
} from "vue-router";

import AdminLayout from "@/layouts/AdminLayout.vue";
import OperatorLayout from "@/layouts/OperatorLayout.vue";
import type { Portal } from "@/services/http";
import { useAuthStore } from "@/stores/auth";

export const routes = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/auth/LoginView.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/admin/login",
    name: "admin-login",
    component: () => import("@/views/auth/AdminLoginView.vue"),
    meta: { public: true, title: "管理后台登录" },
  },
  {
    path: "/change-password",
    name: "change-password",
    component: () => import("@/views/auth/ForcePasswordView.vue"),
    meta: { title: "修改初始密码" },
  },
  {
    path: "/translations",
    component: OperatorLayout,
    children: [
      {
        path: "",
        name: "translations",
        component: () => import("@/views/operator/RecordsView.vue"),
        meta: {
          title: "我的翻译记录",
          navItem: "/translations",
          requiresOperator: true,
        },
      },
      {
        path: "new",
        name: "translation-new",
        component: () => import("@/views/operator/NewTranslationView.vue"),
        meta: {
          title: "新建视频翻译",
          navItem: "/translations/new",
          requiresOperator: true,
        },
      },
      {
        path: ":projectId",
        name: "translation-detail",
        component: () => import("@/views/operator/RecordDetailView.vue"),
        meta: {
          title: "翻译项目详情",
          navItem: "/translations",
          requiresOperator: true,
        },
      },
    ],
  },
  {
    path: "/imagegen",
    component: OperatorLayout,
    children: [
      {
        path: "",
        name: "imagegen",
        component: () => import("@/views/imagegen/ImageGenerateView.vue"),
        meta: {
          title: "图片生成",
          navItem: "/imagegen",
          requiresOperator: true,
        },
      },
    ],
  },
  {
    path: "/videogen",
    component: OperatorLayout,
    children: [
      {
        path: "",
        name: "videogen",
        component: () => import("@/views/videogen/VideoGenerateView.vue"),
        meta: {
          title: "图生视频",
          navItem: "/videogen",
          requiresOperator: true,
          requiresVideogen: true,
        },
      },
    ],
  },
  {
    path: "/admin",
    component: AdminLayout,
    meta: { requiresAdmin: true },
    children: [
      {
        path: "",
        name: "admin-dashboard",
        component: () => import("@/views/admin/DashboardView.vue"),
        meta: {
          title: "运行概览",
          requiresAdmin: true,
          navItem: "/admin",
        },
      },
      {
        path: "accounts",
        name: "admin-accounts",
        component: () => import("@/views/admin/AccountsView.vue"),
        meta: {
          title: "账号管理",
          requiresAdmin: true,
          navItem: "/admin/accounts",
        },
      },
      {
        path: "tasks",
        name: "admin-tasks",
        component: () => import("@/views/admin/TasksView.vue"),
        meta: {
          title: "任务管理",
          requiresAdmin: true,
          navItem: "/admin/tasks",
        },
      },
      {
        path: "providers",
        name: "admin-providers",
        component: () => import("@/views/admin/ProvidersView.vue"),
        meta: {
          title: "接口配置",
          requiresAdmin: true,
          navItem: "/admin/providers",
        },
      },
      {
        path: "costs",
        name: "admin-costs",
        component: () => import("@/views/admin/CostsView.vue"),
        meta: {
          title: "调用费用",
          requiresAdmin: true,
          navItem: "/admin/costs",
        },
      },
      {
        path: "logs",
        name: "admin-logs",
        component: () => import("@/views/admin/LogsView.vue"),
        meta: {
          title: "操作日志",
          requiresAdmin: true,
          navItem: "/admin/logs",
        },
      },
    ],
  },
  { path: "/", redirect: "/translations/new" },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

const PORTAL_HOME: Record<Portal, string> = {
  operator: "/translations/new",
  admin: "/admin",
};

export async function authGuard(to: RouteLocationNormalized) {
  const auth = useAuthStore();
  if (to.name === "change-password") {
    await Promise.all([auth.initialize("operator"), auth.initialize("admin")]);
    const requested: Portal | null =
      to.query.portal === "admin"
        ? "admin"
        : to.query.portal === "operator"
          ? "operator"
          : null;
    const mustChange = (portal: Portal) =>
      auth.accounts[portal]?.mustChangePassword === true;
    const portal =
      (requested && mustChange(requested) ? requested : null) ??
      (mustChange("operator") ? "operator" : null) ??
      (mustChange("admin") ? "admin" : null);
    if (portal) {
      auth.setActivePortal(portal);
      return true;
    }
    if (requested && auth.accounts[requested]) {
      auth.setActivePortal(requested);
      return PORTAL_HOME[requested];
    }
    if (auth.accounts.operator) {
      auth.setActivePortal("operator");
      return PORTAL_HOME.operator;
    }
    if (auth.accounts.admin) {
      auth.setActivePortal("admin");
      return PORTAL_HOME.admin;
    }
    return "/login";
  }
  const portal: Portal = to.path.startsWith("/admin") ? "admin" : "operator";
  auth.setActivePortal(portal);
  await auth.initialize(portal);
  const session = auth.accounts[portal];
  if (to.meta.public) {
    if (session && (to.name === "login" || to.name === "admin-login"))
      return PORTAL_HOME[portal];
    return true;
  }
  if (!session)
    return portal === "admin"
      ? { name: "admin-login", query: { redirect: to.fullPath } }
      : { name: "login", query: { redirect: to.fullPath } };
  if (session.mustChangePassword)
    return { name: "change-password", query: { portal } };
  if (to.meta.requiresVideogen && session.videogenEnabled !== true)
    return PORTAL_HOME.operator;
  return true;
}

export function installAuthGuard(router: Router) {
  router.beforeEach(authGuard);
}

const router = createRouter({
  history: createWebHistory(),
  routes,
});

installAuthGuard(router);

export default router;

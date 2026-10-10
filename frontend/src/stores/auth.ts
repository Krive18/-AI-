import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
  ApiError,
  apiFetch,
  setCsrfToken,
  type Portal,
} from "@/services/http";
import type { Account, AuthPayload } from "@/types/api";

export const useAuthStore = defineStore("auth", () => {
  const accounts = ref<Record<Portal, Account | null>>({
    operator: null,
    admin: null,
  });
  const initializedMap = ref<Record<Portal, boolean>>({
    operator: false,
    admin: false,
  });
  const activePortal = ref<Portal>("operator");
  const loading = ref(false);
  const error = ref("");
  const account = computed(() => accounts.value[activePortal.value]);
  const isAdmin = computed(
    () =>
      activePortal.value === "admin" && accounts.value.admin?.role === 9,
  );

  function setActivePortal(portal: Portal) {
    activePortal.value = portal;
  }

  function accept(payload: AuthPayload, portal: Portal) {
    accounts.value[portal] = payload.account;
    initializedMap.value[portal] = true;
    setCsrfToken(payload.csrfToken, portal);
  }

  function clear(portal: Portal) {
    accounts.value[portal] = null;
    setCsrfToken(null, portal);
  }

  async function initialize(portal: Portal = activePortal.value) {
    if (initializedMap.value[portal]) return;
    try {
      accept(await apiFetch<AuthPayload>("/api/v1/auth/me", { portal }), portal);
    } catch (reason) {
      if (!(reason instanceof ApiError) || reason.status !== 401)
        error.value = "登录状态检查失败";
      clear(portal);
    } finally {
      initializedMap.value[portal] = true;
    }
  }

  async function login(loginName: string, password: string, portal: Portal) {
    loading.value = true;
    error.value = "";
    try {
      accept(
        await apiFetch<AuthPayload>("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ loginName, password, portal }),
          portal,
        }),
        portal,
      );
    } catch (reason) {
      error.value =
        reason instanceof ApiError ? reason.message : "登录服务暂时不可用";
      throw reason;
    } finally {
      loading.value = false;
    }
  }

  async function changePassword(
    currentPassword: string,
    newPassword: string,
    portal: Portal = activePortal.value,
  ) {
    await apiFetch<void>("/api/v1/auth/password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
      portal,
    });
    clear(portal);
  }

  async function logout(portal: Portal = activePortal.value) {
    try {
      await apiFetch<void>("/api/v1/auth/logout", { method: "POST", portal });
    } finally {
      clear(portal);
    }
  }

  return {
    accounts,
    initializedMap,
    activePortal,
    account,
    loading,
    error,
    isAdmin,
    setActivePortal,
    initialize,
    login,
    changePassword,
    logout,
  };
});

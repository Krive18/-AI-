<script setup lang="ts">
import {
  CircleDollarSign,
  Gauge,
  KeyRound,
  ListVideo,
  ScrollText,
  Users,
} from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppHeader from "@/components/AppHeader.vue";
import AppSidebar from "@/components/AppSidebar.vue";
import AppToast from "@/components/AppToast.vue";
import { useAuthStore } from "@/stores/auth";

const open = ref(false);
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const items = [
  { to: "/admin", label: "运行概览", icon: Gauge },
  { to: "/admin/accounts", label: "账号管理", icon: Users },
  { to: "/admin/tasks", label: "任务管理", icon: ListVideo },
  { to: "/admin/providers", label: "接口配置", icon: KeyRound },
  { to: "/admin/costs", label: "调用费用", icon: CircleDollarSign },
  { to: "/admin/logs", label: "操作日志", icon: ScrollText },
];
const title = computed(() => String(route.meta.title ?? "管理后台"));
async function logout() {
  await auth.logout("admin");
  await router.replace("/admin/login");
}
</script>

<template>
  <div class="app-shell app-shell--admin">
    <AppSidebar
      :open="open"
      :items="items"
      section="系统管理"
      @close="open = false"
      @logout="logout"
    />
    <main class="main-shell">
      <AppHeader
        :title="title"
        admin
        @menu="open = true"
      /><RouterView /><AppToast />
    </main>
  </div>
</template>

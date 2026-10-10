<script setup lang="ts">
import { FileClock, FilePlus2, Image, Video } from "@lucide/vue";
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
const items = computed(() => {
  const all = [
    { to: "/translations/new", label: "新建翻译", icon: FilePlus2 },
    { to: "/imagegen", label: "图片生成", icon: Image },
    { to: "/videogen", label: "图生视频", icon: Video },
    { to: "/translations", label: "翻译记录", icon: FileClock },
  ];
  return all.filter(
    (item) => item.to !== "/videogen" || auth.account?.videogenEnabled === true,
  );
});
const title = computed(() => String(route.meta.title ?? "运营工作台"));
async function logout() {
  await auth.logout("operator");
  await router.replace("/login");
}
</script>

<template>
  <div class="app-shell app-shell--operator">
    <AppSidebar
      :open="open"
      :items="items"
      section="翻译工作"
      theme-toggle
      @close="open = false"
      @logout="logout"
    />
    <main class="main-shell">
      <AppHeader :title="title" @menu="open = true" /><RouterView /><AppToast />
    </main>
  </div>
</template>

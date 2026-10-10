<script setup lang="ts">
import { LogOut } from "@lucide/vue";
import type { Component } from "vue";
import { computed } from "vue";
import { useRoute } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import ThemeToggle from "@/components/ThemeToggle.vue";
import { useAuthStore } from "@/stores/auth";

defineProps<{
  open: boolean;
  items: Array<{ to: string; label: string; icon: Component }>;
  section: string;
  themeToggle?: boolean;
}>();
defineEmits<{ close: []; logout: [] }>();
const auth = useAuthStore();
const route = useRoute();
const activeItem = computed(() => String(route.meta.navItem ?? route.path));
</script>

<template>
  <button
    v-if="open"
    class="mobile-backdrop"
    aria-label="关闭导航"
    type="button"
    @click="$emit('close')"
  ></button>
  <aside class="sidebar" :class="{ open }" aria-label="主导航">
    <div class="sidebar-brand">
      <BrandLogo subtitle="智能视频全球化工作台" />
    </div>
    <div class="nav-group">{{ section }}</div>
    <nav class="nav-list">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        class="nav-link"
        :class="{ 'router-link-active': activeItem === item.to }"
        :to="item.to"
        active-class="nav-link--matched"
        exact-active-class="nav-link--exact"
        :aria-current="activeItem === item.to ? 'page' : undefined"
        @click="$emit('close')"
      >
        <component :is="item.icon" aria-hidden="true" /><span>{{
          item.label
        }}</span>
      </RouterLink>
    </nav>
    <div class="sidebar-footer">
      <div class="user-chip">
        <span class="avatar">{{
          auth.account?.displayName.slice(0, 1) || "译"
        }}</span>
        <div class="min-w-0 flex-1">
          <div class="user-name">{{ auth.account?.displayName }}</div>
          <div class="user-role">
            {{ auth.isAdmin ? "管理员" : "运营成员" }}
          </div>
        </div>
        <ThemeToggle v-if="themeToggle" />
        <button
          class="icon-button"
          type="button"
          aria-label="退出登录"
          @click="$emit('logout')"
        >
          <LogOut />
        </button>
      </div>
    </div>
  </aside>
</template>

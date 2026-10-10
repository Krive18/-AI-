<script setup lang="ts">
import { Menu, PanelLeftClose } from "@lucide/vue";

import ThemeToggle from "@/components/ThemeToggle.vue";

defineProps<{ title: string; admin?: boolean }>();
defineEmits<{ menu: [] }>();
</script>

<template>
  <header class="topbar">
    <div class="topbar-title">
      <button
        class="menu-button"
        type="button"
        aria-label="打开导航"
        @click="$emit('menu')"
      >
        <Menu />
      </button>
      <span>{{ title }}</span>
    </div>
    <div v-if="admin" class="topbar-actions">
      <span class="workspace-label"
        ><PanelLeftClose class="mr-1 h-4 w-4" />管理后台</span
      >
      <ThemeToggle />
    </div>
  </header>
</template>

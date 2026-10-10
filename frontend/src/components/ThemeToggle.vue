<script setup lang="ts">
import { Moon, Sun } from "@lucide/vue";
import { computed } from "vue";

import { useThemeStore } from "@/stores/theme";

const theme = useThemeStore();
const isLight = computed(() => theme.mode === "light");
const label = computed(() =>
  isLight.value ? "切换到深色模式" : "切换到浅色模式",
);
</script>

<template>
  <button
    class="icon-button"
    type="button"
    :aria-label="label"
    :title="label"
    @click="theme.toggle()"
  >
    <Sun v-if="isLight" aria-hidden="true" />
    <Moon v-else aria-hidden="true" />
  </button>
</template>

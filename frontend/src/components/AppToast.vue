<script setup lang="ts">
import { CircleAlert, CircleCheck, X } from "@lucide/vue";

import { useToastsStore } from "@/stores/toasts";

const toasts = useToastsStore();
</script>

<template>
  <div class="toast-stack" role="status" aria-live="polite">
    <div
      v-for="toast in toasts.items"
      :key="toast.id"
      class="toast"
      :class="`toast-${toast.kind}`"
    >
      <CircleCheck v-if="toast.kind === 'success'" aria-hidden="true" />
      <CircleAlert v-else aria-hidden="true" />
      <span>{{ toast.message }}</span>
      <button
        class="toast-close"
        type="button"
        aria-label="关闭提示"
        @click="toasts.dismiss(toast.id)"
      >
        <X aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

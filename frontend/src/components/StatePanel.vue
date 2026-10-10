<script setup lang="ts">
import { CircleAlert, Inbox, LoaderCircle } from "@lucide/vue";

defineProps<{
  kind: "loading" | "error" | "empty";
  title: string;
  description: string;
}>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div class="state-panel" :aria-busy="kind === 'loading'" role="status">
    <LoaderCircle
      v-if="kind === 'loading'"
      class="animate-spin"
      aria-hidden="true"
    />
    <CircleAlert v-else-if="kind === 'error'" aria-hidden="true" />
    <Inbox v-else aria-hidden="true" />
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <button
      v-if="kind === 'error'"
      class="btn btn-secondary"
      type="button"
      @click="$emit('retry')"
    >
      重新加载
    </button>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    tone?: "success" | "warning" | "danger" | "info" | "neutral";
  }>(),
  { tone: "neutral" },
);
</script>

<template>
  <span class="badge" :class="`badge-${tone}`">{{ label }}</span>
</template>

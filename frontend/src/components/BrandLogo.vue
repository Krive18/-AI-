<script setup lang="ts">
withDefaults(
  defineProps<{
    compact?: boolean;
    subtitle?: string;
  }>(),
  {
    compact: false,
    subtitle: "",
  },
);
</script>

<template>
  <span class="brand-logo" :class="{ 'brand-logo--compact': compact }">
    <svg
      class="brand-logo__mark"
      viewBox="0 0 52 52"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id="linguasphere-logo-gradient"
          x1="7"
          y1="4"
          x2="46"
          y2="49"
          gradientUnits="userSpaceOnUse"
        >
          <stop stop-color="#29b8ff" />
          <stop offset=".52" stop-color="#427bff" />
          <stop offset="1" stop-color="#9554ff" />
        </linearGradient>
        <filter
          id="linguasphere-logo-glow"
          x="-60%"
          y="-60%"
          width="220%"
          height="220%"
        >
          <feGaussianBlur stdDeviation="2.6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M12 5.75h28A6.25 6.25 0 0 1 46.25 12v21A6.25 6.25 0 0 1 40 39.25H29.4L20 47.2v-7.95h-8A6.25 6.25 0 0 1 5.75 33V12A6.25 6.25 0 0 1 12 5.75Z"
        stroke="url(#linguasphere-logo-gradient)"
        stroke-width="4.2"
        stroke-linejoin="round"
        filter="url(#linguasphere-logo-glow)"
      />
      <path
        d="M18.2 16.2h15.6M26 13v3.2m-6.2 0c1.15 5.55 4.9 9.75 11.25 12.55m.25-12.55c-1.2 5.3-4.8 9.35-10.9 12.2"
        stroke="#9bd2ff"
        stroke-width="2.6"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
    <span class="brand-logo__copy">
      <span class="brand-logo__name"><strong>寰语</strong></span>
      <span v-if="subtitle && !compact" class="brand-logo__subtitle">{{
        subtitle
      }}</span>
    </span>
  </span>
</template>

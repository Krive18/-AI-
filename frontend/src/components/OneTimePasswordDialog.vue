<script setup lang="ts">
import { Check, Copy, KeyRound, X } from "@lucide/vue";
import { nextTick, ref, watch } from "vue";

const props = defineProps<{ password: string | null; accountName: string }>();
const emit = defineEmits<{ close: [] }>();
const copied = ref(false);
const closeButton = ref<HTMLButtonElement | null>(null);

watch(
  () => props.password,
  async (value) => {
    copied.value = false;
    if (value) {
      await nextTick();
      closeButton.value?.focus();
    }
  },
);

async function copyPassword() {
  if (!props.password) return;
  await navigator.clipboard.writeText(props.password);
  copied.value = true;
}
</script>

<template>
  <div v-if="password" class="dialog-backdrop" @click.self="emit('close')">
    <section
      class="dialog-card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="temp-password-title"
    >
      <div class="dialog-heading">
        <span class="brand-mark"><KeyRound /></span
        ><button
          ref="closeButton"
          class="icon-button"
          type="button"
          aria-label="关闭"
          @click="emit('close')"
        >
          <X />
        </button>
      </div>
      <h2 id="temp-password-title">请立即保存临时密码</h2>
      <p>
        {{ accountName }}
        的临时密码关闭后不再显示。首次登录后，系统会要求修改密码。
      </p>
      <div class="password-box">
        <code>{{ password }}</code
        ><button class="btn btn-secondary" type="button" @click="copyPassword">
          <Check v-if="copied" /><Copy v-else />{{ copied ? "已复制" : "复制" }}
        </button>
      </div>
      <button
        class="btn btn-primary w-full"
        type="button"
        @click="emit('close')"
      >
        我已安全保存
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { KeyRound, ShieldCheck } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import { ApiError } from "@/services/http";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const portal = route.query.portal === "admin" ? "admin" : "operator";
const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const loading = ref(false);
const error = ref("");
const valid = computed(() => newPassword.value.length >= 6);

async function submit() {
  error.value = "";
  if (!valid.value) {
    error.value = "新密码至少 6 位。";
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = "两次输入的新密码不一致。";
    return;
  }
  loading.value = true;
  try {
    await auth.changePassword(currentPassword.value, newPassword.value, portal);
    await router.replace(
      portal === "admin"
        ? { path: "/admin/login" }
        : { path: "/login", query: { passwordChanged: "1" } },
    );
  } catch (reason) {
    error.value =
      reason instanceof ApiError
        ? reason.message
        : "密码修改失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="password-page">
    <form class="password-card card" @submit.prevent="submit">
      <BrandLogo compact />
      <span class="auth-icon"><KeyRound /></span>
      <div>
        <span class="workspace-label">首次登录安全校验</span>
        <h1>设置你的正式密码</h1>
        <p>临时密码仅用于首次登录。修改成功后，当前会话将退出。</p>
      </div>
      <div v-if="error" class="form-error" role="alert">{{ error }}</div>
      <div class="field">
        <label for="current-password">当前临时密码</label
        ><input
          id="current-password"
          v-model="currentPassword"
          class="input"
          type="password"
          autocomplete="current-password"
          required
        />
      </div>
      <div class="field">
        <label for="new-password">新密码</label
        ><input
          id="new-password"
          v-model="newPassword"
          class="input"
          type="password"
          autocomplete="new-password"
          minlength="6"
          required
        /><span class="hint">至少 6 位，不限制字符类型。</span>
      </div>
      <div class="field">
        <label for="confirm-password">确认新密码</label
        ><input
          id="confirm-password"
          v-model="confirmPassword"
          class="input"
          type="password"
          autocomplete="new-password"
          required
        />
      </div>
      <button class="btn btn-primary" type="submit" :disabled="loading">
        <ShieldCheck />{{ loading ? "正在保存…" : "保存并重新登录" }}
      </button>
    </form>
  </main>
</template>

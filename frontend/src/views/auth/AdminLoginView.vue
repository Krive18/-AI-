<script setup lang="ts">
import { ArrowRight, Eye, EyeOff, LockKeyhole, UserRound } from "@lucide/vue";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const loginName = ref("");
const password = ref("");
const showPassword = ref(false);

async function submit() {
  const normalizedLoginName = loginName.value.trim();
  try {
    await auth.login(normalizedLoginName, password.value, "admin");
  } catch {
    return;
  }
  const redirect =
    typeof route.query.redirect === "string" ? route.query.redirect : null;
  await router.replace(
    auth.account?.mustChangePassword
      ? "/change-password?portal=admin"
      : (redirect ?? "/admin"),
  );
}
</script>

<template>
  <main class="admin-login-page">
    <section class="admin-login-card card" aria-labelledby="admin-login-title">
      <header class="admin-login-card__header">
        <BrandLogo compact />
        <h1 id="admin-login-title">寰语管理后台</h1>
        <p class="admin-login-card__subtitle">
          内部管理系统，仅限管理员账号
        </p>
      </header>

      <form class="admin-login-form" @submit.prevent="submit">
        <div v-if="auth.error" class="form-error" role="alert">
          {{ auth.error }}
        </div>

        <div class="field">
          <label for="login-name">账号</label>
          <div class="admin-login-input">
            <UserRound aria-hidden="true" />
            <input
              id="login-name"
              v-model="loginName"
              name="loginName"
              class="input"
              type="text"
              autocomplete="username"
              placeholder="请输入管理员账号"
              required
            />
          </div>
        </div>

        <div class="field">
          <label for="password">密码</label>
          <div class="admin-login-input">
            <LockKeyhole aria-hidden="true" />
            <input
              id="password"
              v-model="password"
              name="password"
              class="input"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
              required
            />
            <button
              class="admin-login-input__toggle"
              data-testid="password-toggle"
              type="button"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              :aria-pressed="showPassword"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" aria-hidden="true" />
              <Eye v-else aria-hidden="true" />
            </button>
          </div>
        </div>

        <button class="btn btn-primary" type="submit" :disabled="auth.loading">
          <span>{{ auth.loading ? "正在验证…" : "登录管理后台" }}</span>
          <ArrowRight aria-hidden="true" />
        </button>
      </form>

      <p class="admin-login-card__footer">
        <RouterLink to="/login">运营工作台登录 →</RouterLink>
      </p>
    </section>
  </main>
</template>

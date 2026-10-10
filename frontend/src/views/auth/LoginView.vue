<script setup lang="ts">
import {
  ArrowRight,
  AudioLines,
  Captions,
  Eye,
  EyeOff,
  LockKeyhole,
  ShieldCheck,
  UserRound,
} from "@lucide/vue";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import BrandLogo from "@/components/BrandLogo.vue";
import TranslationGlobe from "@/components/TranslationGlobe.vue";
import { useAuthStore } from "@/stores/auth";

const REMEMBERED_LOGIN_NAME_KEY = "linguasphere.rememberedLoginName";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const loginName = ref(readRememberedLoginName());
const password = ref("");
const rememberLoginName = ref(Boolean(loginName.value));
const showPassword = ref(false);

function readRememberedLoginName() {
  try {
    return window.localStorage.getItem(REMEMBERED_LOGIN_NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

function updateRememberedLoginName(value: string) {
  try {
    if (rememberLoginName.value) {
      window.localStorage.setItem(REMEMBERED_LOGIN_NAME_KEY, value);
    } else {
      window.localStorage.removeItem(REMEMBERED_LOGIN_NAME_KEY);
    }
  } catch {
    /* Login remains available if storage is disabled by the browser. */
  }
}

async function submit() {
  const normalizedLoginName = loginName.value.trim();
  try {
    await auth.login(normalizedLoginName, password.value, "operator");
  } catch {
    return;
  }
  updateRememberedLoginName(normalizedLoginName);
  const redirect =
    typeof route.query.redirect === "string" ? route.query.redirect : null;
  await router.replace(
    auth.account?.mustChangePassword
      ? "/change-password?portal=operator"
      : (redirect ?? "/translations/new"),
  );
}
</script>

<template>
  <main class="login-page">
    <div class="login-page__shell">
      <header class="login-page__header">
        <BrandLogo />
      </header>

      <div class="login-layout">
        <section class="login-hero" aria-labelledby="login-hero-title">
          <div class="login-hero__copy">
            <h1 id="login-hero-title">
              开启<span>智能</span>翻译工作流
            </h1>
            <p>
              面向全球化团队的智能视频全球化工作台，统一管理转写、翻译、字幕与配音，让每一次交付更高效。
            </p>

            <ul class="login-capabilities" aria-label="平台能力">
              <li><AudioLines aria-hidden="true" /><span>智能转写</span></li>
              <li><Captions aria-hidden="true" /><span>术语一致</span></li>
              <li><ShieldCheck aria-hidden="true" /><span>安全协作</span></li>
            </ul>
          </div>
          <div class="login-hero__globe">
            <TranslationGlobe />
          </div>
        </section>

        <aside class="login-panel-column" aria-label="登录区域">
          <div class="login-frame">
            <section class="login-card">
              <h2>登录平台</h2>
              <p class="login-card__subtitle">请输入管理员分配的内部账号以继续</p>

              <form class="login-form" @submit.prevent="submit">
                <div
                  v-if="route.query.passwordChanged"
                  class="success-note"
                  role="status"
                >
                  密码已修改，请使用新密码登录。
                </div>
                <div v-if="auth.error" class="form-error" role="alert">
                  {{ auth.error }}
                </div>

                <div class="login-field">
                  <label for="login-name">账号</label>
                  <div class="login-input-shell">
                    <UserRound aria-hidden="true" />
                    <input
                      id="login-name"
                      v-model="loginName"
                      name="loginName"
                      type="text"
                      autocomplete="username"
                      placeholder="请输入管理员分配的账号"
                      required
                    />
                  </div>
                </div>

                <div class="login-field">
                  <label for="password">密码</label>
                  <div class="login-input-shell">
                    <LockKeyhole aria-hidden="true" />
                    <input
                      id="password"
                      v-model="password"
                      name="password"
                      :type="showPassword ? 'text' : 'password'"
                      autocomplete="current-password"
                      placeholder="请输入密码"
                      required
                    />
                    <button
                      class="login-password-toggle"
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

                <div class="login-options">
                  <label class="login-checkbox" for="remember-login-name">
                    <input
                      id="remember-login-name"
                      v-model="rememberLoginName"
                      type="checkbox"
                    />
                    <span>记住账号</span>
                  </label>
                  <span class="login-account-note">内部员工账号</span>
                </div>

                <button
                  class="login-submit"
                  type="submit"
                  :disabled="auth.loading"
                >
                  <span>{{ auth.loading ? "正在验证…" : "登录工作台" }}</span>
                  <ArrowRight aria-hidden="true" />
                </button>
              </form>

              <p class="login-card__footer">
                <RouterLink to="/admin/login">管理后台登录 →</RouterLink>
              </p>
            </section>
          </div>

          <p class="login-security-note">
            <ShieldCheck aria-hidden="true" />
            <span>无法登录？请联系公司系统管理员重置密码。</span>
          </p>
        </aside>
      </div>
    </div>
  </main>
</template>

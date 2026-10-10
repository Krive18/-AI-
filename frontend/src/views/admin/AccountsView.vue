<script setup lang="ts">
import {
  KeyRound,
  Plus,
  RefreshCcw,
  ShieldOff,
  UserRoundCheck,
  Video,
  VideoOff,
} from "@lucide/vue";
import { onMounted, ref } from "vue";

import OneTimePasswordDialog from "@/components/OneTimePasswordDialog.vue";
import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { ApiError } from "@/services/http";
import { formatDateTime } from "@/utils/datetime";
import {
  createAccount,
  listAccounts,
  resetAccountPassword,
  revokeAccountSessions,
  setVideogenPermission,
  updateAccount,
} from "@/services/adminAccounts";
import { useAuthStore } from "@/stores/auth";
import type { Account } from "@/types/api";

const auth = useAuthStore();
const accounts = ref<Account[]>([]);
const loading = ref(true);
const actionLoading = ref("");
const error = ref("");
const nextCursor = ref<number | null>(null);
const showCreate = ref(false);
const loginName = ref("");
const displayName = ref("");
const role = ref<1 | 9>(1);
const temporaryPassword = ref<string | null>(null);
const passwordAccount = ref("");

function message(reason: unknown) {
  return reason instanceof ApiError
    ? reason.message
    : "请求未完成，请稍后重试。";
}
async function load(cursor?: number) {
  loading.value = true;
  error.value = "";
  try {
    const response = await listAccounts(cursor);
    accounts.value = cursor
      ? [...accounts.value, ...response.items]
      : response.items;
    nextCursor.value = response.nextCursor;
  } catch (reason) {
    error.value = message(reason);
  } finally {
    loading.value = false;
  }
}
async function submitCreate() {
  actionLoading.value = "create";
  error.value = "";
  try {
    const response = await createAccount({
      loginName: loginName.value.trim(),
      displayName: displayName.value.trim(),
      role: role.value,
    });
    accounts.value.unshift(response.account);
    passwordAccount.value = response.account.displayName;
    temporaryPassword.value = response.temporaryPassword;
    showCreate.value = false;
    loginName.value = "";
    displayName.value = "";
    role.value = 1;
  } catch (reason) {
    error.value = message(reason);
  } finally {
    actionLoading.value = "";
  }
}
function replaceAccount(account: Account) {
  accounts.value = accounts.value.map((item) =>
    item.publicId === account.publicId ? account : item,
  );
}
async function toggleStatus(account: Account) {
  actionLoading.value = account.publicId;
  error.value = "";
  try {
    replaceAccount(
      (await updateAccount(account, { status: account.status === 1 ? 2 : 1 }))
        .account,
    );
  } catch (reason) {
    error.value = message(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function toggleVideogen(account: Account) {
  actionLoading.value = account.publicId;
  error.value = "";
  try {
    replaceAccount(
      (await setVideogenPermission(account, !account.videogenEnabled)).account,
    );
  } catch (reason) {
    error.value = message(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function resetPassword(account: Account) {
  actionLoading.value = account.publicId;
  error.value = "";
  try {
    const response = await resetAccountPassword(account);
    replaceAccount(response.account);
    passwordAccount.value = response.account.displayName;
    temporaryPassword.value = response.temporaryPassword;
  } catch (reason) {
    error.value = message(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function revoke(account: Account) {
  actionLoading.value = account.publicId;
  error.value = "";
  try {
    replaceAccount((await revokeAccountSessions(account)).account);
  } catch (reason) {
    error.value = message(reason);
  } finally {
    actionLoading.value = "";
  }
}
function closePassword() {
  temporaryPassword.value = null;
  passwordAccount.value = "";
}
onMounted(() => load());
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>账号管理</h1>
        <p>创建内部账号、管理启停状态，并在必要时撤销登录会话或重置密码。</p>
      </div>
      <button
        class="btn btn-primary"
        type="button"
        @click="showCreate = !showCreate"
      >
        <Plus />新增账号
      </button>
    </header>
    <div v-if="error" class="form-error page-alert" role="alert">
      {{ error }}
    </div>
    <section v-if="showCreate" class="card create-account-card">
      <div class="card-header">
        <h2>新增内部账号</h2>
        <span class="hint">提交后临时密码只显示一次</span>
      </div>
      <form class="card-body account-form" @submit.prevent="submitCreate">
        <div class="field">
          <label for="account-login">登录名</label
          ><input
            id="account-login"
            v-model="loginName"
            class="input"
            required
            maxlength="64"
            autocomplete="off"
          />
        </div>
        <div class="field">
          <label for="account-display">显示名称</label
          ><input
            id="account-display"
            v-model="displayName"
            class="input"
            required
            maxlength="64"
          />
        </div>
        <div class="field">
          <label for="account-role">角色</label
          ><select id="account-role" v-model="role" class="select">
            <option :value="1">运营成员</option>
            <option :value="9">管理员</option>
          </select>
        </div>
        <div class="account-form-actions">
          <button
            class="btn btn-secondary"
            type="button"
            @click="showCreate = false"
          >
            取消</button
          ><button
            class="btn btn-primary"
            type="submit"
            :disabled="actionLoading === 'create'"
          >
            {{ actionLoading === "create" ? "正在创建…" : "创建账号" }}
          </button>
        </div>
      </form>
    </section>
    <section class="card">
      <StatePanel
        v-if="loading && !accounts.length"
        kind="loading"
        title="正在加载账号"
        description="正在从账号服务读取最新数据。"
      /><StatePanel
        v-else-if="error && !accounts.length"
        kind="error"
        title="账号数据加载失败"
        :description="error"
        @retry="load()"
      /><StatePanel
        v-else-if="!accounts.length"
        kind="empty"
        title="还没有内部账号"
        description="点击“新增账号”创建第一位运营成员。"
      />
      <div v-else class="table-wrap">
        <table class="data-table accounts-table">
          <thead>
            <tr>
              <th>账号</th>
              <th>角色</th>
              <th>状态</th>
              <th>安全状态</th>
              <th>图生视频</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="account in accounts" :key="account.publicId">
              <td data-label="账号">
                <strong>{{ account.displayName }}</strong>
                <div class="cell-note">{{ account.loginName }}</div>
              </td>
              <td data-label="角色">
                {{ account.role === 9 ? "管理员" : "运营成员" }}
              </td>
              <td data-label="状态">
                <StatusBadge
                  :label="account.status === 1 ? '启用' : '停用'"
                  :tone="account.status === 1 ? 'success' : 'neutral'"
                />
              </td>
              <td data-label="安全状态">
                <StatusBadge
                  :label="
                    account.mustChangePassword ? '待修改初始密码' : '正常'
                  "
                  :tone="account.mustChangePassword ? 'warning' : 'success'"
                />
              </td>
              <td data-label="图生视频">
                <StatusBadge
                  :label="account.videogenEnabled ? '已开通' : '未开通'"
                  :tone="account.videogenEnabled ? 'success' : 'neutral'"
                />
              </td>
              <td data-label="创建时间">
                {{
                  account.createdAt ? formatDateTime(account.createdAt) : "—"
                }}
              </td>
              <td>
                <div class="row-actions">
                  <button
                    class="action-button"
                    type="button"
                    :disabled="actionLoading === account.publicId"
                    @click="resetPassword(account)"
                  >
                    <KeyRound />重置密码</button
                  ><button
                    class="action-button"
                    type="button"
                    :disabled="actionLoading === account.publicId"
                    @click="revoke(account)"
                  >
                    <RefreshCcw />撤销会话</button
                  ><button
                    class="action-button"
                    type="button"
                    :disabled="actionLoading === account.publicId"
                    @click="toggleVideogen(account)"
                  >
                    <VideoOff v-if="account.videogenEnabled" /><Video
                      v-else
                    />{{
                      account.videogenEnabled ? "关闭图生视频" : "开通图生视频"
                    }}</button
                  ><button
                    class="action-button"
                    type="button"
                    :disabled="
                      account.publicId === auth.account?.publicId ||
                      actionLoading === account.publicId
                    "
                    @click="toggleStatus(account)"
                  >
                    <UserRoundCheck v-if="account.status === 2" /><ShieldOff
                      v-else
                    />{{ account.status === 1 ? "停用" : "启用" }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="nextCursor" class="load-more">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="loading"
          @click="load(nextCursor ?? undefined)"
        >
          {{ loading ? "加载中…" : "加载更多" }}
        </button>
      </div>
    </section>
    <OneTimePasswordDialog
      :password="temporaryPassword"
      :account-name="passwordAccount"
      @close="closePassword"
    />
  </div>
</template>

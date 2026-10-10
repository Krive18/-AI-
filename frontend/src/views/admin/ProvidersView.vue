<script setup lang="ts">
import {
  History,
  KeyRound,
  Pencil,
  PlugZap,
  Plus,
  RefreshCcw,
  ShieldCheck,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import ProviderEditor from "@/components/provider/ProviderEditor.vue";
import ProviderHistoryPanel from "@/components/provider/ProviderHistoryPanel.vue";
import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  createProvider,
  listProviders,
  testProvider,
  updateProvider,
  type ProviderConfig,
  type ProviderCreateInput,
  type ProviderUpdateInput,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";

const providers = ref<ProviderConfig[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const actionLoading = ref("");
const formMode = ref<"create" | "edit" | null>(null);
const editingId = ref("");
const selectedId = ref("");
const editorSeed = ref(0);
const testResults = ref<Record<string, string>>({});

const capabilityLabels: Record<number, string> = {
  1: "语音识别 ASR",
  2: "文本翻译",
  3: "语音合成 TTS",
  4: "一体化同声传译",
  5: "图片生成",
  6: "字幕识别",
  7: "视频生成",
};
const editing = computed(
  () =>
    providers.value.find((provider) => provider.publicId === editingId.value) ??
    null,
);
const selected = computed(
  () =>
    providers.value.find(
      (provider) => provider.publicId === selectedId.value,
    ) ?? null,
);

function friendly(reason: unknown) {
  return reason instanceof ApiError ? reason.message : "供应商配置请求未完成。";
}
function replaceProvider(provider: ProviderConfig) {
  providers.value = providers.value.map((item) =>
    item.publicId === provider.publicId ? provider : item,
  );
}
function closeForm() {
  editingId.value = "";
  formMode.value = null;
}
function openCreate() {
  editingId.value = "";
  selectedId.value = "";
  formMode.value = "create";
  editorSeed.value += 1;
}
function openEdit(provider: ProviderConfig) {
  editingId.value = provider.publicId;
  selectedId.value = "";
  formMode.value = "edit";
  editorSeed.value += 1;
}
function openHistory(provider: ProviderConfig) {
  closeForm();
  selectedId.value =
    selectedId.value === provider.publicId ? "" : provider.publicId;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    providers.value = (await listProviders()).items;
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    loading.value = false;
  }
}

async function save(payload: ProviderCreateInput | ProviderUpdateInput) {
  error.value = "";
  notice.value = "";
  actionLoading.value = "form";
  try {
    if (formMode.value === "create") {
      const result = await createProvider(payload as ProviderCreateInput);
      providers.value.push(result.provider);
      notice.value = `${result.provider.displayName} 已创建。`;
    } else if (editing.value) {
      const result = await updateProvider(
        editing.value,
        payload as ProviderUpdateInput,
      );
      replaceProvider(result.provider);
      notice.value = `${result.provider.displayName} 已更新。`;
    }
    closeForm();
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}

async function toggle(provider: ProviderConfig) {
  actionLoading.value = provider.publicId;
  error.value = "";
  notice.value = "";
  try {
    const result = await updateProvider(provider, {
      status: provider.status === 1 ? 2 : 1,
    });
    replaceProvider(result.provider);
    notice.value = `${provider.displayName} 已${result.provider.status === 1 ? "启用" : "停用"}。`;
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}

async function test(provider: ProviderConfig) {
  actionLoading.value = provider.publicId;
  error.value = "";
  try {
    testResults.value[provider.publicId] = (
      await testProvider(provider.publicId)
    ).result;
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}

function activated(provider: ProviderConfig) {
  replaceProvider(provider);
  notice.value = `${provider.displayName} 的生效版本已切换。`;
}
onMounted(load);
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>接口配置</h1>
        <p>
          维护专业精译和智能翻译所需的真实接口，并按不可变版本配置计费规则。
        </p>
      </div>
      <button class="btn btn-primary" type="button" @click="openCreate">
        <Plus />新增供应商
      </button>
    </header>
    <div v-if="error" class="form-error page-alert" role="alert">
      {{ error }}
    </div>
    <div v-if="notice" class="success-note page-alert" role="status">
      {{ notice }}
    </div>
    <ProviderEditor
      v-if="formMode"
      :key="`${formMode}-${editingId}-${editorSeed}`"
      :mode="formMode"
      :provider="editing"
      :loading="actionLoading === 'form'"
      @cancel="closeForm"
      @save="save"
    />

    <StatePanel
      v-if="loading"
      kind="loading"
      title="正在加载供应商"
      description="正在读取当前生效的供应商配置。"
    />
    <StatePanel
      v-else-if="error && !providers.length"
      kind="error"
      title="供应商加载失败"
      :description="error"
      @retry="load"
    />
    <StatePanel
      v-else-if="!providers.length"
      kind="empty"
      title="尚未配置供应商"
      description="当前没有真实供应商。请按使用路径新增专业精译或智能翻译接口，再执行远程连接检查。"
    />
    <div v-else class="provider-list">
      <article
        v-for="provider in providers"
        :key="provider.publicId"
        class="card provider-card"
        :class="{ 'provider-card-selected': selectedId === provider.publicId }"
      >
        <div class="provider-icon"><PlugZap /></div>
        <div>
          <div class="heading-line">
            <h2>{{ provider.displayName }}</h2>
            <StatusBadge
              :label="provider.status === 1 ? '已启用' : '已停用'"
              :tone="provider.status === 1 ? 'success' : 'neutral'"
            />
          </div>
          <p>
            {{ capabilityLabels[provider.capability] }} · 优先级
            {{ provider.priority }}
          </p>
          <span class="hint"
            >密钥：{{ provider.hasKey ? "已安全配置" : "未配置" }} ·
            生效版本：{{ provider.activeVersionId ?? "无" }} ·
            “已启用”仅表示参与任务路由</span
          >
          <div
            v-if="testResults[provider.publicId]"
            class="provider-test-result"
          >
            <ShieldCheck />连接检查：{{
              testResults[provider.publicId] === "CONNECTED"
                ? "远程接口已验证"
                : testResults[provider.publicId]
            }}
          </div>
        </div>
        <div class="provider-actions">
          <button
            class="btn btn-secondary"
            type="button"
            @click="openEdit(provider)"
          >
            <Pencil />编辑</button
          ><button
            class="btn btn-secondary"
            type="button"
            :disabled="actionLoading === provider.publicId"
            @click="test(provider)"
          >
            <RefreshCcw />检查</button
          ><button
            class="btn btn-secondary"
            type="button"
            :disabled="actionLoading === provider.publicId"
            @click="toggle(provider)"
          >
            {{ provider.status === 1 ? "停用" : "启用" }}</button
          ><button
            class="btn btn-secondary"
            type="button"
            :aria-expanded="selectedId === provider.publicId"
            @click="openHistory(provider)"
          >
            <History />版本与价格
          </button>
        </div>
      </article>
    </div>

    <ProviderHistoryPanel
      v-if="selected"
      :provider="selected"
      @close="selectedId = ''"
      @activated="activated"
    />
    <section class="card security-note">
      <KeyRound />
      <div>
        <h2>凭据安全边界</h2>
        <p>
          页面只提交新密钥，不展示服务端掩码或密文；options
          仅保存运行所需的非敏感参数。创建版本、启停、激活与连接检查均由管理员接口审计。
        </p>
      </div>
    </section>
  </div>
</template>

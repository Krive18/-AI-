<script setup lang="ts">
import { ArrowRight, Plus, RefreshCcw, RotateCcw, Search } from "@lucide/vue";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { ApiError } from "@/services/http";
import {
  listProjects,
  retryProject,
  type TranslationProject,
} from "@/services/projects";
import { useToastsStore } from "@/stores/toasts";
import { formatDate, formatDateTime } from "@/utils/datetime";

const POLL_INTERVAL_MS = 4000;
const SEARCH_DEBOUNCE_MS = 300;
const RETRY_CONFIRM_MS = 3000;
// Terminal states follow the backend ProjectStatus enum: 7 已完成, 8 部分完成,
// 9 失败, 11 已取消. Everything else is still in flight and drives polling.
const TERMINAL_STATUSES = new Set([7, 8, 9, 11]);
const FAILED_STATUS = 9;

type StateFilter = "all" | "processing" | "succeeded" | "failed";

const toasts = useToastsStore();
const projects = ref<TranslationProject[]>([]);
const nextCursor = ref<number | null>(null);
const loading = ref(true);
const error = ref("");
const stateFilter = ref<StateFilter>("all");
const searchInput = ref("");
const keyword = ref("");
const confirmRetryId = ref<string | null>(null);
const retryingId = ref<string | null>(null);
const statuses: Record<
  number,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  1: { label: "草稿", tone: "neutral" },
  2: { label: "上传中", tone: "info" },
  3: { label: "校验中", tone: "info" },
  4: { label: "提取音频", tone: "info" },
  5: { label: "语音识别", tone: "info" },
  6: { label: "处理中", tone: "info" },
  7: { label: "已完成", tone: "success" },
  8: { label: "部分完成", tone: "warning" },
  9: { label: "失败", tone: "danger" },
  10: { label: "取消中", tone: "warning" },
  11: { label: "已取消", tone: "neutral" },
};
const filterOptions: { value: StateFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "processing", label: "进行中" },
  { value: "succeeded", label: "已完成" },
  { value: "failed", label: "失败" },
];
const translationModes = {
  professional: "专业精译",
  youdao: "智能翻译",
  subtitle: "字幕翻译",
} as const;

let pollTimer: ReturnType<typeof setInterval> | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let confirmTimer: ReturnType<typeof setTimeout> | undefined;

const hasActiveProjects = computed(() =>
  projects.value.some((project) => !TERMINAL_STATUSES.has(project.status)),
);

function status(value: number) {
  return (
    statuses[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
function isFailedRow(value: number) {
  return value === FAILED_STATUS || value === 11;
}
function absoluteTime(value: string) {
  return formatDateTime(value);
}
function relativeTime(value: string) {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const utc = new Date(
    normalized.endsWith("Z") ? normalized : `${normalized}Z`,
  ).getTime();
  const elapsed = Date.now() - utc;
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days <= 7) return `${days} 天前`;
  return formatDate(value);
}
function size(value: number) {
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(2)} GB`
    : `${(value / 1024 ** 2).toFixed(1)} MB`;
}
async function load(cursor?: number) {
  loading.value = true;
  error.value = "";
  try {
    const page = await listProjects(cursor, {
      keyword: keyword.value || undefined,
      state: stateFilter.value === "all" ? undefined : stateFilter.value,
    });
    projects.value = cursor ? [...projects.value, ...page.items] : page.items;
    nextCursor.value = page.nextCursor;
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "翻译记录暂时无法加载。";
  } finally {
    loading.value = false;
  }
}
function reload() {
  nextCursor.value = null;
  projects.value = [];
  void load();
}
function syncPolling() {
  if (hasActiveProjects.value && !pollTimer) {
    pollTimer = setInterval(() => {
      if (!loading.value) void load();
    }, POLL_INTERVAL_MS);
  } else if (!hasActiveProjects.value && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
}
async function onRetry(project: TranslationProject) {
  if (confirmRetryId.value !== project.publicId) {
    confirmRetryId.value = project.publicId;
    if (confirmTimer) clearTimeout(confirmTimer);
    confirmTimer = setTimeout(() => {
      confirmRetryId.value = null;
    }, RETRY_CONFIRM_MS);
    return;
  }
  confirmRetryId.value = null;
  if (confirmTimer) clearTimeout(confirmTimer);
  retryingId.value = project.publicId;
  try {
    await retryProject(project.publicId);
    toasts.push("已重新提交", "success");
    await load();
  } catch (reason) {
    toasts.push(
      reason instanceof ApiError
        ? reason.message
        : "重试提交失败，请稍后重试。",
      "error",
    );
  } finally {
    retryingId.value = null;
  }
}

watch([stateFilter, keyword], reload);
watch(projects, syncPolling);
watch(searchInput, (value) => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    keyword.value = value.trim();
  }, SEARCH_DEBOUNCE_MS);
});
onMounted(() => void load());
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
  if (searchTimer) clearTimeout(searchTimer);
  if (confirmTimer) clearTimeout(confirmTimer);
});
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>我的翻译记录</h1>
        <p>查看已提交项目的总进度、处理状态和交付结果。</p>
      </div>
      <div class="heading-actions">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="loading"
          @click="load()"
        >
          <RefreshCcw />刷新</button
        ><RouterLink class="btn btn-primary" to="/translations/new"
          ><Plus />新建翻译</RouterLink
        >
      </div>
    </header>
    <section class="card">
      <div class="card-header">
        <div>
          <h2>翻译项目</h2>
          <span class="hint">按创建时间倒序展示</span>
        </div>
      </div>
      <div class="records-toolbar">
        <div class="chip-group" role="group" aria-label="按状态筛选">
          <button
            v-for="option in filterOptions"
            :key="option.value"
            class="chip"
            :class="{ 'chip-active': stateFilter === option.value }"
            type="button"
            :aria-pressed="stateFilter === option.value"
            @click="stateFilter = option.value"
          >
            {{ option.label }}
          </button>
        </div>
        <div class="records-search">
          <Search aria-hidden="true" />
          <input
            v-model="searchInput"
            class="input"
            type="search"
            placeholder="搜索项目名或文件名"
            aria-label="搜索项目名或文件名"
          />
        </div>
      </div>
      <div
        v-if="loading && !projects.length"
        class="records-skeleton"
        aria-busy="true"
      >
        <div v-for="n in 4" :key="n" class="skeleton"></div>
      </div>
      <StatePanel
        v-else-if="error && !projects.length"
        kind="error"
        title="翻译记录加载失败"
        :description="error"
        @retry="load()"
      /><StatePanel
        v-else-if="!projects.length"
        kind="empty"
        title="没有符合条件的翻译记录"
        description="调整筛选条件，或点击“新建翻译”上传第一个中文视频。"
      /><RouterLink
        v-if="!loading && !error && !projects.length"
        class="btn btn-primary records-empty-action"
        to="/translations/new"
        ><Plus />新建翻译</RouterLink
      ><template v-else
        ><div v-if="error" class="form-error table-alert" role="alert">
          {{ error }}
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>项目 / 文件</th>
                <th>文件大小</th>
                <th>进度</th>
                <th>状态</th>
                <th>创建时间</th>
                <th><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="project in projects"
                :key="project.publicId"
                :class="{ 'row-failed': isFailedRow(project.status) }"
              >
                <td data-label="项目 / 文件">
                  <strong>{{ project.name }}</strong>
                  <div class="cell-note">
                    {{ translationModes[project.translationMode] }}
                  </div>
                </td>
                <td data-label="文件大小">
                  {{ size(project.sourceSizeBytes) }}
                </td>
                <td data-label="进度">
                  <div class="progress">
                    <span
                      :style="{ width: `${project.progressPercent}%` }"
                    ></span>
                  </div>
                  <span class="cell-note"
                    >{{ project.progressPercent }}%<template
                      v-if="!TERMINAL_STATUSES.has(project.status)"
                      >&nbsp;· {{ status(project.status).label }}</template
                    ></span
                  >
                </td>
                <td data-label="状态">
                  <StatusBadge
                    :label="status(project.status).label"
                    :tone="status(project.status).tone"
                  />
                </td>
                <td
                  data-label="创建时间"
                  :title="absoluteTime(project.createdAt)"
                >
                  {{ relativeTime(project.createdAt) }}
                </td>
                <td>
                  <div class="row-actions">
                    <button
                      v-if="project.status === FAILED_STATUS"
                      class="btn btn-secondary btn-compact"
                      :class="{
                        'retry-confirm': confirmRetryId === project.publicId,
                      }"
                      type="button"
                      :disabled="retryingId === project.publicId"
                      @click="onRetry(project)"
                    >
                      <RotateCcw v-if="confirmRetryId !== project.publicId" />{{
                        confirmRetryId === project.publicId
                          ? "确认重试？"
                          : retryingId === project.publicId
                            ? "提交中…"
                            : "重试"
                      }}</button
                    ><RouterLink
                      class="table-link"
                      :to="{
                        name: 'translation-detail',
                        params: { projectId: project.publicId },
                      }"
                      >查看<ArrowRight
                    /></RouterLink>
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
        </div></template
      >
    </section>
  </div>
</template>

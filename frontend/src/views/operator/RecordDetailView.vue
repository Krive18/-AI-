<script setup lang="ts">
import {
  ArrowLeft,
  Ban,
  Captions,
  Check,
  Copy,
  Download,
  FileVideo2,
  Languages,
  Play,
  RefreshCcw,
  RotateCcw,
} from "@lucide/vue";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { ApiError } from "@/services/http";
import {
  cancelProject,
  downloadProjectAsset,
  fetchTaskSubtitles,
  getProject,
  previewProjectVideoUrl,
  retryProject,
  retryProjectTask,
  taskSubtitlePreviewUrl,
  type TaskSubtitles,
  type TranslationProject,
  type TranslationSubtask,
} from "@/services/projects";
import { formatDateTime } from "@/utils/datetime";

const route = useRoute();
const projectId = computed(() => String(route.params.projectId ?? ""));
const project = ref<TranslationProject | null>(null);
const tasks = ref<TranslationSubtask[]>([]);
const loading = ref(true);
const actionLoading = ref("");
const error = ref("");
const notice = ref("");
const previewTaskId = ref("");
let timer: ReturnType<typeof setInterval> | undefined;
const projectStatuses: Record<
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
const taskStatuses: Record<
  number,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  1: { label: "排队中", tone: "warning" },
  2: { label: "翻译中", tone: "info" },
  3: { label: "配音中", tone: "info" },
  4: { label: "导出中", tone: "info" },
  5: { label: "已完成", tone: "success" },
  6: { label: "失败", tone: "danger" },
  7: { label: "取消中", tone: "warning" },
  8: { label: "已取消", tone: "neutral" },
};
const stageLabels: Record<number, string> = {
  1: "等待处理",
  2: "文本翻译",
  3: "语音合成",
  4: "视频导出",
  5: "处理完成",
};
const translationModes = {
  professional: "专业精译",
  youdao: "智能翻译",
  subtitle: "字幕翻译",
} as const;
const languageLabels: Record<string, string> = {
  "en-US": "英语（美国）",
  "ja-JP": "日语",
  "ko-KR": "韩语",
  "vi-VN": "越南语",
  "ms-MY": "马来语",
  "th-TH": "泰语",
  "en-SG": "英语（新加坡）",
  "fil-PH": "菲律宾语",
  "de-DE": "德语",
  "fr-FR": "法语",
};
const canCancel = computed(() =>
  Boolean(project.value && ![7, 8, 9, 11].includes(project.value.status)),
);
const canRetryProject = computed(() =>
  Boolean(project.value && [8, 9].includes(project.value.status)),
);
const shouldPoll = computed(
  () =>
    Boolean(project.value && ![7, 8, 9, 11].includes(project.value.status)) ||
    tasks.value.some((task) => [1, 2, 3, 4, 7].includes(task.status)),
);
const previewTask = computed(() =>
  tasks.value.find((task) => task.publicId === previewTaskId.value),
);
const previewUrl = computed(() =>
  previewTask.value
    ? previewProjectVideoUrl(projectId.value, previewTask.value.publicId)
    : "",
);
const subtitles = ref<TaskSubtitles | null>(null);
const copiedSource = ref(false);
const copiedTarget = ref(false);
let copyResetTimer: ReturnType<typeof setTimeout> | undefined;
const subtitlePreviewUrl = computed(() =>
  previewTask.value
    ? taskSubtitlePreviewUrl(projectId.value, previewTask.value.publicId)
    : "",
);
const canDownloadSrt = computed(
  () =>
    Boolean(previewTask.value && previewTask.value.status === 5) &&
    (subtitles.value?.segment_count ?? 0) > 0,
);

function status(map: typeof projectStatuses, value: number) {
  return map[value] ?? { label: `状态 ${value}`, tone: "neutral" as const };
}
function stageLabel(task: TranslationSubtask) {
  if (project.value?.translationMode === "subtitle" && task.stage === 2)
    return "字幕识别";
  return stageLabels[task.stage] ?? `阶段 ${task.stage}`;
}
function date(value: string) {
  return formatDateTime(value);
}
function size(value: number) {
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(2)} GB`
    : `${(value / 1024 ** 2).toFixed(1)} MB`;
}
function friendly(reason: unknown) {
  return reason instanceof ApiError
    ? reason.message
    : "请求未完成，请稍后重试。";
}
async function load(silent = false) {
  if (!silent) loading.value = true;
  error.value = "";
  try {
    const detail = await getProject(projectId.value);
    project.value = detail.project;
    tasks.value = detail.tasks;
    if (silent && !shouldPoll.value) notice.value = "";
    if (
      !tasks.value.some(
        (task) => task.publicId === previewTaskId.value && task.status === 5,
      )
    ) {
      previewTaskId.value =
        tasks.value.find((task) => task.status === 5)?.publicId ?? "";
    }
    await loadSubtitles();
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    if (!silent) loading.value = false;
  }
}
async function loadSubtitles() {
  const taskId = previewTaskId.value;
  if (!taskId) {
    subtitles.value = null;
    return;
  }
  try {
    subtitles.value = await fetchTaskSubtitles(projectId.value, taskId);
  } catch {
    subtitles.value = null;
  }
}
function selectPreview(task: TranslationSubtask) {
  previewTaskId.value = task.publicId;
  void loadSubtitles();
}
async function copySubtitles(field: "source" | "target") {
  const text = subtitles.value
    ? field === "source"
      ? subtitles.value.source_text
      : subtitles.value.target_text
    : "";
  if (!text) return;
  await navigator.clipboard.writeText(text);
  if (field === "source") copiedSource.value = true;
  else copiedTarget.value = true;
  if (copyResetTimer) clearTimeout(copyResetTimer);
  copyResetTimer = setTimeout(() => {
    copiedSource.value = false;
    copiedTarget.value = false;
  }, 1500);
}
async function cancel() {
  if (
    !project.value ||
    !globalThis.confirm("确认取消这个翻译项目？已开始的处理将进入取消流程。")
  )
    return;
  actionLoading.value = "cancel";
  error.value = "";
  notice.value = "";
  try {
    project.value = (await cancelProject(project.value.publicId)).project;
    notice.value = "已提交取消请求。";
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function retry(task: TranslationSubtask) {
  actionLoading.value = task.publicId;
  error.value = "";
  notice.value = "";
  try {
    const result = await retryProjectTask(projectId.value, task.publicId);
    tasks.value = tasks.value.map((item) =>
      item.publicId === result.task.publicId ? result.task : item,
    );
    notice.value = `${languageLabels[task.language] ?? task.language}任务已重新排队。`;
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function retryWholeProject() {
  if (!project.value) return;
  actionLoading.value = "retry-project";
  error.value = "";
  notice.value = "";
  try {
    project.value = (await retryProject(project.value.publicId)).project;
    notice.value = "项目已从共享处理阶段重新排队。";
    await load(true);
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}
async function download(task: TranslationSubtask, kind: "video" | "subtitle") {
  actionLoading.value = `${task.publicId}-${kind}`;
  error.value = "";
  try {
    const result = await downloadProjectAsset(
      projectId.value,
      task.publicId,
      kind,
    );
    const fallback = `${project.value?.name ?? "translation"}-${task.language}.${kind === "video" ? "mp4" : "srt"}`;
    const filename = (result.filename ?? fallback)
      .replace(/[\\/:*?"<>|]/g, "_")
      .slice(0, 180);
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}
onMounted(() => {
  void load();
  timer = globalThis.setInterval(() => {
    if (shouldPoll.value && !actionLoading.value) void load(true);
  }, 3000);
});
onUnmounted(() => {
  if (timer) globalThis.clearInterval(timer);
  if (copyResetTimer) clearTimeout(copyResetTimer);
});
</script>

<template>
  <div class="page">
    <RouterLink class="back-link" to="/translations">
      <ArrowLeft />返回翻译记录 </RouterLink
    ><StatePanel
      v-if="loading"
      kind="loading"
      title="正在加载项目"
      description="正在读取项目与各语言子任务状态。"
    /><StatePanel
      v-else-if="error && !project"
      kind="error"
      title="项目加载失败"
      :description="error"
      @retry="load()"
    /><template v-else-if="project">
      <header class="page-heading">
        <div>
          <div class="heading-line">
            <h1>{{ project.name }}</h1>
            <StatusBadge
              :label="status(projectStatuses, project.status).label"
              :tone="status(projectStatuses, project.status).tone"
            />
          </div>
          <p>
            {{ project.sourceFilename }} · {{ project.publicId }} ·
            {{ translationModes[project.translationMode] }} ·
            {{ date(project.createdAt) }}
          </p>
        </div>
        <div class="heading-actions">
          <button
            class="btn btn-secondary"
            type="button"
            :disabled="loading"
            @click="load()"
          >
            <RefreshCcw />刷新</button
          ><button
            v-if="canRetryProject"
            class="btn btn-secondary"
            type="button"
            :disabled="actionLoading === 'retry-project'"
            @click="retryWholeProject"
          >
            <RotateCcw />{{
              actionLoading === "retry-project" ? "重新排队中…" : "重试整个项目"
            }}</button
          ><button
            v-if="canCancel"
            class="btn btn-danger"
            type="button"
            :disabled="actionLoading === 'cancel'"
            @click="cancel"
          >
            <Ban />{{ actionLoading === "cancel" ? "取消中…" : "取消项目" }}
          </button>
        </div>
      </header>
      <div v-if="error" class="form-error page-alert" role="alert">
        {{ error }}
      </div>
      <div v-if="notice" class="success-note page-alert" role="status">
        {{ notice }}
      </div>
      <div class="grid-2">
        <article class="card stat">
          <FileVideo2 class="stat-icon" />
          <div class="stat-label">源视频大小</div>
          <div class="stat-value small">
            {{ size(project.sourceSizeBytes) }}
          </div>
        </article>
        <article class="card stat">
          <Languages class="stat-icon" />
          <div class="stat-label">目标语言</div>
          <div class="stat-value small">{{ tasks.length }} 种</div>
        </article>
      </div>
      <section class="card detail-section">
        <div class="card-header">
          <h2>项目总进度</h2>
          <strong>{{ project.progressPercent }}%</strong>
        </div>
        <div class="card-body">
          <div class="progress large">
            <span :style="{ width: `${project.progressPercent}%` }"></span>
          </div>
          <span class="hint progress-note">
            {{
              shouldPoll
                ? "处理中项目每 3 秒自动刷新。"
                : "项目状态已停止自动刷新。"
            }}
          </span>
        </div>
      </section>
      <section v-if="previewTask" class="card detail-section">
        <div class="card-header">
          <div>
            <h2>成片预览</h2>
            <span class="hint">{{
              languageLabels[previewTask.language] ?? previewTask.language
            }}</span>
          </div>
        </div>
        <div class="card-body">
          <video
            :key="previewUrl"
            class="output-preview"
            :src="previewUrl"
            controls
            preload="metadata"
          >
            <track
              v-if="previewTask.status === 5"
              kind="subtitles"
              :src="subtitlePreviewUrl"
              :label="`${languageLabels[previewTask.language] ?? previewTask.language}字幕`"
              default
            />
            当前浏览器不支持视频预览，请直接下载成片。
          </video>
        </div>
      </section>
      <section v-if="tasks.length" class="card detail-section">
        <div class="card-header">
          <h2>字幕文本</h2>
          <span class="hint">{{ subtitles?.segment_count ?? 0 }} 段</span>
        </div>
        <div class="card-body subtitle-text-grid">
          <article class="subtitle-text-card">
            <div class="subtitle-text-heading">
              <h3>翻译前字幕</h3>
              <button
                class="btn btn-secondary"
                type="button"
                @click="copySubtitles('source')"
              >
                <Check v-if="copiedSource" /><Copy v-else />{{
                  copiedSource ? "已复制" : "复制"
                }}
              </button>
            </div>
            <p class="subtitle-text-body">
              {{ subtitles?.source_text || "暂无字幕" }}
            </p>
          </article>
          <article class="subtitle-text-card">
            <div class="subtitle-text-heading">
              <h3>翻译后字幕</h3>
              <div class="subtitle-text-actions">
                <button
                  v-if="canDownloadSrt && previewTask"
                  class="btn btn-secondary"
                  type="button"
                  :disabled="
                    actionLoading === `${previewTask.publicId}-subtitle`
                  "
                  @click="download(previewTask, 'subtitle')"
                >
                  <Captions />下载 SRT
                </button>
                <button
                  class="btn btn-secondary"
                  type="button"
                  @click="copySubtitles('target')"
                >
                  <Check v-if="copiedTarget" /><Copy v-else />{{
                    copiedTarget ? "已复制" : "复制"
                  }}
                </button>
              </div>
            </div>
            <p class="subtitle-text-body">
              {{ subtitles?.target_text || "暂无字幕" }}
            </p>
          </article>
        </div>
      </section>
      <section class="card detail-section">
        <div class="card-header">
          <h2>语言子任务</h2>
          <span class="hint">{{ tasks.length }} 个任务</span>
        </div>
        <StatePanel
          v-if="!tasks.length"
          kind="empty"
          title="尚未生成语言任务"
          description="项目校验完成后会展示各目标语言处理状态。"
        />
        <div v-else class="task-card-list">
          <article
            v-for="task in tasks"
            :key="task.publicId"
            class="subtask-card"
          >
            <div class="subtask-heading">
              <div>
                <strong>{{
                  languageLabels[task.language] ?? task.language
                }}</strong
                ><span
                  >{{ stageLabel(task) }} · 重试 {{ task.retryCount }} 次</span
                >
              </div>
              <StatusBadge
                :label="status(taskStatuses, task.status).label"
                :tone="status(taskStatuses, task.status).tone"
              />
            </div>
            <div class="progress large">
              <span :style="{ width: `${task.progressPercent}%` }"></span>
            </div>
            <div v-if="task.errorCode" class="subtask-error">
              <strong>{{ task.errorCode }}</strong
              ><span>{{ task.errorMessage }}</span>
            </div>
            <div class="subtask-actions">
              <button
                v-if="task.status === 6 && project.status !== 9"
                class="btn btn-secondary"
                type="button"
                :disabled="actionLoading === task.publicId"
                @click="retry(task)"
              >
                <RotateCcw />{{
                  actionLoading === task.publicId
                    ? "重新排队中…"
                    : "重试失败任务"
                }}</button
              ><template v-if="task.status === 5">
                <button
                  class="btn btn-secondary"
                  type="button"
                  :disabled="previewTaskId === task.publicId"
                  @click="selectPreview(task)"
                >
                  <Play />{{
                    previewTaskId === task.publicId ? "正在预览" : "预览成片"
                  }}
                </button>
                <button
                  class="btn btn-secondary"
                  type="button"
                  :disabled="actionLoading === `${task.publicId}-video`"
                  @click="download(task, 'video')"
                >
                  <Download />下载视频</button
                ><button
                  class="btn btn-secondary"
                  type="button"
                  :disabled="actionLoading === `${task.publicId}-subtitle`"
                  @click="download(task, 'subtitle')"
                >
                  <Captions />下载 SRT
                </button>
              </template>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

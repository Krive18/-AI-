<script setup lang="ts">
import { Ban, Download, ExternalLink, Filter, RotateCcw } from "@lucide/vue";
import { onMounted, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  cancelAdminTask,
  downloadAdminImageGeneration,
  downloadAdminVideoGeneration,
  listAdminImageGenerations,
  listAdminTasks,
  listAdminVideoGenerations,
  retryAdminTask,
  type AdminImageGenerationJob,
  type AdminTask,
  type AdminVideoGenerationJob,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";
import { formatDateTime } from "@/utils/datetime";

const IMAGE_PAGE_SIZE = 20;
const VIDEO_PAGE_SIZE = 20;

type TaskTab = "translation" | "image" | "video";
const activeTab = ref<TaskTab>("translation");
const tasks = ref<AdminTask[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const actionLoading = ref("");
const nextCursor = ref<number | null>(null);
const statusFilter = ref("");
const languageFilter = ref("");
const imageJobs = ref<AdminImageGenerationJob[]>([]);
const lightbox = ref<{ srcs: string[]; index: number } | null>(null);
const imageLoading = ref(false);
const imageError = ref("");
const imageHasMore = ref(false);
const videoJobs = ref<AdminVideoGenerationJob[]>([]);
const videoPreview = ref<AdminVideoGenerationJob | null>(null);
const videoLoading = ref(false);
const videoError = ref("");
const videoHasMore = ref(false);
const statuses: Record<
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
const locales = [
  ["en-US", "英语（美国）"],
  ["ja-JP", "日语"],
  ["ko-KR", "韩语"],
  ["vi-VN", "越南语"],
  ["ms-MY", "马来语"],
  ["th-TH", "泰语"],
  ["en-SG", "英语（新加坡）"],
  ["fil-PH", "菲律宾语"],
  ["de-DE", "德语"],
  ["fr-FR", "法语"],
];
const translationModes = {
  professional: "专业精译",
  youdao: "智能翻译",
  subtitle: "字幕翻译",
} as const;
const imageStatuses: Record<
  number,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  1: { label: "排队中", tone: "neutral" },
  2: { label: "生成中", tone: "info" },
  3: { label: "已完成", tone: "success" },
  4: { label: "失败", tone: "danger" },
};

function imageStatus(value: number) {
  return (
    imageStatuses[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
function promptSummary(value: string) {
  return value.length > 30 ? `${value.slice(0, 30)}…` : value;
}
const videoTierLabels: Record<number, string> = {
  1: "标准版",
  2: "快速版",
  3: "轻量版",
};
async function loadVideoJobs(append = false) {
  videoLoading.value = true;
  videoError.value = "";
  try {
    const page = await listAdminVideoGenerations(
      VIDEO_PAGE_SIZE,
      append ? videoJobs.value.length : 0,
    );
    videoJobs.value = append ? [...videoJobs.value, ...page.items] : page.items;
    videoHasMore.value = page.items.length === VIDEO_PAGE_SIZE;
  } catch (reason) {
    videoError.value =
      reason instanceof ApiError ? reason.message : "生视频任务暂时无法加载。";
  } finally {
    videoLoading.value = false;
  }
}
async function saveVideo(job: AdminVideoGenerationJob) {
  try {
    const { blob, filename } = await downloadAdminVideoGeneration(job.publicId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ?? `${job.publicId}.mp4`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    videoError.value = "视频下载失败，请稍后重试。";
  }
}
async function loadImageJobs(append = false) {
  imageLoading.value = true;
  imageError.value = "";
  try {
    const page = await listAdminImageGenerations(
      IMAGE_PAGE_SIZE,
      append ? imageJobs.value.length : 0,
    );
    imageJobs.value = append ? [...imageJobs.value, ...page.items] : page.items;
    imageHasMore.value = page.items.length === IMAGE_PAGE_SIZE;
  } catch (reason) {
    imageError.value =
      reason instanceof ApiError ? reason.message : "生图任务暂时无法加载。";
  } finally {
    imageLoading.value = false;
  }
}
function chooseTab(tab: TaskTab) {
  activeTab.value = tab;
  if (tab === "image" && !imageJobs.value.length && !imageError.value) {
    void loadImageJobs();
  }
  if (tab === "video" && !videoJobs.value.length && !videoError.value) {
    void loadVideoJobs();
  }
}
async function saveImage(job: AdminImageGenerationJob, index: number) {
  try {
    const { blob, filename } = await downloadAdminImageGeneration(
      job.publicId,
      index,
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ?? `${job.publicId}-${index + 1}.png`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    imageError.value = "图片下载失败，请稍后重试。";
  }
}
function status(value: number) {
  return (
    statuses[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
function formatDate(value: string) {
  return formatDateTime(value);
}
async function load(cursor?: number) {
  loading.value = true;
  error.value = "";
  try {
    const page = await listAdminTasks({
      cursor,
      status: statusFilter.value ? Number(statusFilter.value) : undefined,
      language: languageFilter.value || undefined,
    });
    tasks.value = cursor ? [...tasks.value, ...page.items] : page.items;
    nextCursor.value = page.nextCursor;
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "翻译任务暂时无法加载。";
  } finally {
    loading.value = false;
  }
}
async function act(task: AdminTask, action: "cancel" | "retry") {
  if (
    action === "cancel" &&
    !globalThis.confirm(
      `确认取消 ${task.projectName} 的 ${task.language} 任务？`,
    )
  )
    return;
  actionLoading.value = `${task.publicId}-${action}`;
  error.value = "";
  notice.value = "";
  try {
    const result =
      action === "cancel"
        ? await cancelAdminTask(task.publicId)
        : await retryAdminTask(task.publicId);
    tasks.value = tasks.value.map((item) =>
      item.publicId === task.publicId ? { ...item, ...result.task } : item,
    );
    notice.value =
      action === "cancel" ? "任务已进入取消流程。" : "失败任务已重新排队。";
  } catch (reason) {
    error.value =
      reason instanceof ApiError
        ? reason.message
        : "任务操作未完成，请稍后重试。";
  } finally {
    actionLoading.value = "";
  }
}
onMounted(() => load());
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>任务管理</h1>
        <p>
          按处理状态和目标语言查看全局翻译任务，或查看全公司员工的图片生成记录。
        </p>
      </div>
    </header>
    <div class="log-tabs" role="tablist" aria-label="任务类型">
      <button
        :class="{ active: activeTab === 'translation' }"
        role="tab"
        type="button"
        @click="chooseTab('translation')"
      >
        翻译任务</button
      ><button
        :class="{ active: activeTab === 'image' }"
        role="tab"
        type="button"
        @click="chooseTab('image')"
      >
        生图任务</button
      ><button
        :class="{ active: activeTab === 'video' }"
        role="tab"
        type="button"
        @click="chooseTab('video')"
      >
        生视频任务
      </button>
    </div>
    <template v-if="activeTab === 'translation'">
      <div v-if="notice" class="success-note page-alert" role="status">
        {{ notice }}
      </div>
      <div
        v-if="error && tasks.length"
        class="form-error page-alert"
        role="alert"
      >
        {{ error }}
      </div>
      <section class="card">
        <form class="card-header filter-bar" @submit.prevent="load()">
          <select
            v-model="statusFilter"
            class="select compact-select"
            aria-label="任务状态"
          >
            <option value="">全部状态</option>
            <option
              v-for="(item, value) in statuses"
              :key="value"
              :value="value"
            >
              {{ item.label }}
            </option></select
          ><select
            v-model="languageFilter"
            class="select compact-select"
            aria-label="目标语言"
          >
            <option value="">全部语言</option>
            <option
              v-for="locale in locales"
              :key="locale[0]"
              :value="locale[0]"
            >
              {{ locale[1] }}
            </option></select
          ><button class="btn btn-secondary" type="submit" :disabled="loading">
            <Filter />应用筛选
          </button>
        </form>
        <StatePanel
          v-if="loading && !tasks.length"
          kind="loading"
          title="正在加载任务"
          description="正在读取最新任务状态。"
        /><StatePanel
          v-else-if="error && !tasks.length"
          kind="error"
          title="任务加载失败"
          :description="error"
          @retry="load()"
        /><StatePanel
          v-else-if="!tasks.length"
          kind="empty"
          title="没有符合条件的任务"
          description="请调整筛选条件，或等待运营端创建翻译任务。"
        />
        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>项目</th>
                <th>语言</th>
                <th>翻译方式</th>
                <th>阶段 / 进度</th>
                <th>重试</th>
                <th>状态</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in tasks" :key="task.publicId">
                <td data-label="任务">
                  <strong>{{ task.publicId }}</strong>
                  <div v-if="task.errorCode" class="cell-note error-text">
                    {{ task.errorCode }} · {{ task.errorMessage }}
                  </div>
                </td>
                <td data-label="项目">
                  <RouterLink
                    class="table-link"
                    :to="`/translations/${task.projectPublicId}`"
                    >{{ task.projectName }} <ExternalLink
                  /></RouterLink>
                  <div class="cell-note">
                    #{{ task.projectId }} · 账号 #{{ task.createdBy }}
                  </div>
                </td>
                <td data-label="语言">{{ task.language }}</td>
                <td data-label="翻译方式">
                  {{ translationModes[task.translationMode] }}
                </td>
                <td data-label="阶段 / 进度">
                  阶段 {{ task.stage }} · {{ task.progressPercent }}%
                </td>
                <td data-label="重试">{{ task.retryCount }}</td>
                <td data-label="状态">
                  <StatusBadge
                    :label="status(task.status).label"
                    :tone="status(task.status).tone"
                  />
                </td>
                <td data-label="更新时间">{{ formatDate(task.updatedAt) }}</td>
                <td data-label="操作">
                  <div class="table-actions">
                    <button
                      v-if="[1, 2, 3, 4, 7].includes(task.status)"
                      class="btn btn-secondary"
                      type="button"
                      :disabled="Boolean(actionLoading)"
                      @click="act(task, 'cancel')"
                    >
                      <Ban />{{
                        actionLoading === `${task.publicId}-cancel`
                          ? "取消中…"
                          : "取消"
                      }}</button
                    ><button
                      v-if="task.status === 6"
                      class="btn btn-secondary"
                      type="button"
                      :disabled="Boolean(actionLoading)"
                      @click="act(task, 'retry')"
                    >
                      <RotateCcw />{{
                        actionLoading === `${task.publicId}-retry`
                          ? "重试中…"
                          : "重试"
                      }}
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
    </template>
    <section v-else-if="activeTab === 'image'" class="card">
      <div class="card-header">
        <div>
          <h2>生图任务</h2>
          <span class="hint">全公司员工的图片生成记录，按创建时间倒序展示</span>
        </div>
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="imageLoading"
          @click="loadImageJobs()"
        >
          刷新
        </button>
      </div>
      <StatePanel
        v-if="imageLoading && !imageJobs.length"
        kind="loading"
        title="正在加载生图任务"
        description="正在读取最新生成记录。"
      /><StatePanel
        v-else-if="imageError && !imageJobs.length"
        kind="error"
        title="生图任务加载失败"
        :description="imageError"
        @retry="loadImageJobs()"
      /><StatePanel
        v-else-if="!imageJobs.length"
        kind="empty"
        title="暂无生图任务"
        description="员工端生成的图片任务会保留在这里。"
      />
      <template v-else>
        <div v-if="imageError" class="form-error table-alert" role="alert">
          {{ imageError }}
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>创建时间</th>
                <th>用户</th>
                <th>描述词</th>
                <th>张数</th>
                <th>分辨率</th>
                <th>参考图</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="job in imageJobs"
                :key="job.publicId"
                :class="{ 'row-failed': job.status === 4 }"
              >
                <td data-label="创建时间">{{ formatDate(job.createdAt) }}</td>
                <td data-label="用户">
                  <strong>{{ job.accountDisplayName }}</strong>
                  <div class="cell-note">{{ job.accountLoginName }}</div>
                </td>
                <td data-label="描述词">
                  <strong :title="job.prompt">{{
                    promptSummary(job.prompt)
                  }}</strong>
                  <div v-if="job.errorCode" class="cell-note error-text">
                    {{ job.errorCode }} · {{ job.errorMessage }}
                  </div>
                </td>
                <td data-label="张数">{{ job.count }}</td>
                <td data-label="分辨率">{{ job.size }}</td>
                <td data-label="参考图">{{ job.referenceCount }} 张</td>
                <td data-label="状态">
                  <StatusBadge
                    :label="imageStatus(job.status).label"
                    :tone="imageStatus(job.status).tone"
                  />
                </td>
                <td data-label="操作">
                  <div class="table-actions">
                    <button
                      v-if="job.outputs.length"
                      class="btn btn-secondary"
                      type="button"
                      @click="lightbox = { srcs: job.outputs, index: 0 }"
                    >
                      预览
                    </button>
                    <button
                      v-for="(output, index) in job.outputs"
                      :key="output"
                      class="btn btn-secondary"
                      type="button"
                      @click="saveImage(job, index)"
                    >
                      <Download />第 {{ index + 1 }} 张
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <div v-if="imageHasMore" class="load-more">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="imageLoading"
          @click="loadImageJobs(true)"
        >
          {{ imageLoading ? "加载中…" : "加载更多" }}
        </button>
      </div>
    </section>
    <section v-else class="card">
      <div class="card-header">
        <div>
          <h2>生视频任务</h2>
          <span class="hint">全公司员工的图生视频记录，按创建时间倒序展示</span>
        </div>
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="videoLoading"
          @click="loadVideoJobs()"
        >
          刷新
        </button>
      </div>
      <StatePanel
        v-if="videoLoading && !videoJobs.length"
        kind="loading"
        title="正在加载生视频任务"
        description="正在读取最新生成记录。"
      /><StatePanel
        v-else-if="videoError && !videoJobs.length"
        kind="error"
        title="生视频任务加载失败"
        :description="videoError"
        @retry="loadVideoJobs()"
      /><StatePanel
        v-else-if="!videoJobs.length"
        kind="empty"
        title="暂无生视频任务"
        description="员工端生成的视频任务会保留在这里。"
      />
      <template v-else>
        <div v-if="videoError" class="form-error table-alert" role="alert">
          {{ videoError }}
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>创建时间</th>
                <th>用户</th>
                <th>描述词</th>
                <th>档位</th>
                <th>分辨率</th>
                <th>时长</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="job in videoJobs"
                :key="job.publicId"
                :class="{ 'row-failed': job.status === 4 }"
              >
                <td data-label="创建时间">{{ formatDate(job.createdAt) }}</td>
                <td data-label="用户">
                  <strong>{{ job.accountDisplayName }}</strong>
                  <div class="cell-note">{{ job.accountLoginName }}</div>
                </td>
                <td data-label="描述词">
                  <strong :title="job.prompt">{{
                    promptSummary(job.prompt)
                  }}</strong>
                  <div v-if="job.errorCode" class="cell-note error-text">
                    {{ job.errorCode }} · {{ job.errorMessage }}
                  </div>
                </td>
                <td data-label="档位">
                  {{ videoTierLabels[job.tier] ?? "-" }}
                </td>
                <td data-label="分辨率">{{ job.size.toUpperCase() }}</td>
                <td data-label="时长">{{ job.durationSeconds }} 秒</td>
                <td data-label="状态">
                  <StatusBadge
                    :label="imageStatus(job.status).label"
                    :tone="imageStatus(job.status).tone"
                  />
                </td>
                <td data-label="操作">
                  <div class="table-actions">
                    <button
                      v-if="job.outputs.length"
                      class="btn btn-secondary"
                      type="button"
                      @click="videoPreview = job"
                    >
                      预览
                    </button>
                    <button
                      v-if="job.outputs.length"
                      class="btn btn-secondary"
                      type="button"
                      @click="saveVideo(job)"
                    >
                      <Download />下载
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <div v-if="videoHasMore" class="load-more">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="videoLoading"
          @click="loadVideoJobs(true)"
        >
          {{ videoLoading ? "加载中…" : "加载更多" }}
        </button>
      </div>
    </section>
    <ImageLightbox
      v-if="lightbox"
      :srcs="lightbox.srcs"
      :index="lightbox.index"
      @close="lightbox = null"
    />
    <div
      v-if="videoPreview"
      class="video-preview-backdrop"
      role="dialog"
      aria-label="视频预览"
      @click.self="videoPreview = null"
    >
      <div class="video-preview-dialog">
        <div class="card-header">
          <div>
            <h2>视频预览</h2>
            <span class="hint">{{ promptSummary(videoPreview.prompt) }}</span>
          </div>
          <button
            class="btn btn-secondary"
            type="button"
            @click="videoPreview = null"
          >
            关闭
          </button>
        </div>
        <video
          class="video-preview-player"
          :src="videoPreview.outputs[0]"
          controls
          autoplay
          playsinline
        ></video>
      </div>
    </div>
  </div>
</template>

<style scoped>
.video-preview-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  background: rgb(3 7 19 / 86%);
  padding: 24px;
}
.video-preview-dialog {
  width: min(720px, 100%);
  background: var(--surface, #fff);
  border-radius: 14px;
  padding: 16px;
  display: grid;
  gap: 12px;
}
.video-preview-player {
  width: 100%;
  border-radius: 10px;
  background: #000;
}
</style>

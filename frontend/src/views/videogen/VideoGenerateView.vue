<script setup lang="ts">
import {
  ChevronDown,
  ChevronUp,
  Download,
  ImagePlus,
  LoaderCircle,
  RefreshCcw,
  X,
} from "@lucide/vue";
import { computed, onMounted, onUnmounted, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { ApiError } from "@/services/http";
import {
  createVideoGeneration,
  downloadVideo,
  getVideoGeneration,
  listVideoGenerations,
  type VideoGenerationJob,
  type VideoResolution,
  type VideoTier,
} from "@/services/videogen";
import { useAuthStore } from "@/stores/auth";
import { useToastsStore } from "@/stores/toasts";
import { formatDateTime } from "@/utils/datetime";

const POLL_INTERVAL_MS = 3000;
const TERMINAL_STATUSES = new Set([3, 4]);

const auth = useAuthStore();
const toasts = useToastsStore();
const prompt = ref("");
const tier = ref<VideoTier>(2);
const resolution = ref<VideoResolution>("720p");
const durationSeconds = ref(5);
const reference = ref<{ name: string; dataUrl: string } | null>(null);
const dragging = ref(false);
const submitting = ref(false);
const currentJob = ref<VideoGenerationJob | null>(null);
const jobs = ref<VideoGenerationJob[]>([]);
const historyLoading = ref(true);
const historyError = ref("");
const expandedId = ref<string | null>(null);
let pollTimer: ReturnType<typeof setInterval> | undefined;

const generating = computed(
  () =>
    currentJob.value !== null &&
    !TERMINAL_STATUSES.has(currentJob.value.status),
);
const videogenAllowed = computed(() => auth.account?.videogenEnabled === true);

const statuses: Record<
  number,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  1: { label: "排队中", tone: "neutral" },
  2: { label: "生成中", tone: "info" },
  3: { label: "已完成", tone: "success" },
  4: { label: "失败", tone: "danger" },
};
const tierOptions: Array<{ value: VideoTier; label: string }> = [
  { value: 1, label: "标准版" },
  { value: 2, label: "快速版" },
  { value: 3, label: "轻量版" },
];
const resolutionOptions: Array<{ value: VideoResolution; label: string }> = [
  { value: "480p", label: "480P" },
  { value: "720p", label: "720P" },
];
// Seedance 2.0 系列单段上限 15 秒;接入更长时长模型后再放开 20/25/30
const durationOptions = [5, 10, 15];

function status(value: number) {
  return (
    statuses[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
function tierLabel(value: number) {
  return tierOptions.find((option) => option.value === value)?.label ?? "-";
}
function absoluteTime(value: string) {
  return formatDateTime(value);
}
function promptSummary(value: string) {
  return value.length > 30 ? `${value.slice(0, 30)}…` : value;
}
function addFile(file: File) {
  if (!file.type.startsWith("image/")) {
    toasts.push("参考图必须是图片文件", "error");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    reference.value = { name: file.name, dataUrl: String(reader.result) };
  };
  reader.readAsDataURL(file);
}
function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files?.length) addFile(input.files[0]);
  input.value = "";
}
function onDrop(event: DragEvent) {
  dragging.value = false;
  const file = event.dataTransfer?.files?.[0];
  if (file) addFile(file);
}
function removeReference() {
  reference.value = null;
}
async function submit() {
  if (!prompt.value.trim()) {
    toasts.push("请填写视频描述", "error");
    return;
  }
  if (!reference.value) {
    toasts.push("请上传一张参考图作为首帧", "error");
    return;
  }
  if (submitting.value) return;
  submitting.value = true;
  try {
    const result = await createVideoGeneration({
      prompt: prompt.value.trim(),
      tier: tier.value,
      resolution: resolution.value,
      durationSeconds: durationSeconds.value,
      reference: reference.value.dataUrl,
    });
    currentJob.value = result.job;
    startPolling();
  } catch (reason) {
    toasts.push(
      reason instanceof ApiError ? reason.message : "提交失败，请稍后重试。",
      "error",
    );
  } finally {
    submitting.value = false;
  }
}
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, POLL_INTERVAL_MS);
}
async function poll() {
  if (!currentJob.value) {
    stopPolling();
    return;
  }
  try {
    const result = await getVideoGeneration(currentJob.value.publicId);
    currentJob.value = result.job;
    if (TERMINAL_STATUSES.has(result.job.status)) {
      stopPolling();
      await loadHistory();
    }
  } catch {
    // 保持轮询，网络恢复后自动继续
  }
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
}
async function loadHistory() {
  historyLoading.value = true;
  historyError.value = "";
  try {
    const page = await listVideoGenerations(20);
    jobs.value = page.items;
  } catch (reason) {
    historyError.value =
      reason instanceof ApiError ? reason.message : "生成记录暂时无法加载。";
  } finally {
    historyLoading.value = false;
  }
}
async function saveVideo(job: VideoGenerationJob) {
  try {
    const { blob, filename } = await downloadVideo(job.publicId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ?? `${job.publicId}.mp4`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    toasts.push("视频下载失败，请稍后重试。", "error");
  }
}
function toggleExpand(publicId: string) {
  expandedId.value = expandedId.value === publicId ? null : publicId;
}

onMounted(() => {
  if (videogenAllowed.value) void loadHistory();
});
onUnmounted(stopPolling);
</script>

<template>
  <div class="page">
    <StatePanel
      v-if="!videogenAllowed"
      kind="error"
      title="当前账号未开通图生视频权限"
      description="请联系管理员开通后再使用该功能。"
    />
    <template v-else>
      <header class="page-heading">
        <div>
          <h1>图生视频</h1>
          <p>
            上传一张参考图作为首帧，配合描述词生成短视频；画幅自动跟随参考图。
          </p>
        </div>
      </header>

      <div class="videogen-workspace">
        <section class="card videogen-panel">
          <div class="card-body">
            <form class="videogen-form" @submit.prevent="submit">
              <div class="field">
                <label for="videogen-prompt">描述词</label>
                <textarea
                  id="videogen-prompt"
                  v-model="prompt"
                  class="textarea"
                  rows="5"
                  maxlength="2000"
                  placeholder="描述想要的动态画面，例如：镜头缓慢推进，猫咪抬头看向窗外，微风吹动窗帘"
                ></textarea>
                <span class="hint">{{ prompt.length }}/2000</span>
              </div>
              <div class="field">
                <label>参考图（必填，作为视频首帧）</label>
                <label
                  v-if="!reference"
                  class="upload-zone"
                  :class="{ 'upload-zone-active': dragging }"
                  for="videogen-reference-file"
                  @dragover.prevent="dragging = true"
                  @dragleave.prevent="dragging = false"
                  @drop.prevent="onDrop"
                >
                  <ImagePlus aria-hidden="true" />
                  <span>点击或拖拽上传 1 张图片</span>
                  <input
                    id="videogen-reference-file"
                    type="file"
                    accept="image/*"
                    aria-label="上传参考图"
                    @change="onFileChange"
                  />
                </label>
                <div v-else class="videogen-reference">
                  <img :src="reference.dataUrl" :alt="reference.name" />
                  <button
                    class="videogen-reference-remove"
                    type="button"
                    :aria-label="`删除 ${reference.name}`"
                    @click="removeReference"
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
                <span class="hint">竖图生成竖屏视频，横图生成横屏视频。</span>
              </div>
              <div class="field">
                <label>生成档位</label>
                <div class="chip-group" role="group" aria-label="生成档位">
                  <button
                    v-for="option in tierOptions"
                    :key="option.value"
                    class="chip"
                    :class="{ 'chip-active': tier === option.value }"
                    type="button"
                    :aria-pressed="tier === option.value"
                    @click="tier = option.value"
                  >
                    {{ option.label }}
                  </button>
                </div>
              </div>
              <div class="field">
                <label>分辨率</label>
                <div class="chip-group" role="group" aria-label="分辨率">
                  <button
                    v-for="option in resolutionOptions"
                    :key="option.value"
                    class="chip"
                    :class="{ 'chip-active': resolution === option.value }"
                    type="button"
                    :aria-pressed="resolution === option.value"
                    @click="resolution = option.value"
                  >
                    {{ option.label }}
                  </button>
                </div>
              </div>
              <div class="field">
                <label>时长</label>
                <div class="chip-group" role="group" aria-label="时长">
                  <button
                    v-for="option in durationOptions"
                    :key="option"
                    class="chip"
                    :class="{ 'chip-active': durationSeconds === option }"
                    type="button"
                    :aria-pressed="durationSeconds === option"
                    @click="durationSeconds = option"
                  >
                    {{ option }} 秒
                  </button>
                </div>
              </div>
              <div class="videogen-actions">
                <button
                  class="btn btn-primary btn-block"
                  type="submit"
                  :disabled="submitting || generating"
                >
                  <LoaderCircle v-if="submitting" class="animate-spin" />
                  {{
                    generating ? "生成中…" : submitting ? "提交中…" : "生成视频"
                  }}
                </button>
              </div>
            </form>
          </div>
        </section>

        <section class="card videogen-stage">
          <div class="card-header">
            <div>
              <h2>生成结果</h2>
              <span v-if="currentJob" class="hint">{{
                promptSummary(currentJob.prompt)
              }}</span>
            </div>
            <div class="videogen-stage-tools">
              <StatusBadge
                v-if="currentJob"
                :label="status(currentJob.status).label"
                :tone="status(currentJob.status).tone"
              />
              <button
                v-if="currentJob && currentJob.status === 3"
                class="btn btn-secondary btn-compact"
                type="button"
                @click="saveVideo(currentJob)"
              >
                <Download />下载视频
              </button>
            </div>
          </div>
          <div class="card-body">
            <StatePanel
              v-if="!currentJob"
              kind="empty"
              title="尚未生成视频"
              description="在左侧上传参考图并填写描述词，点击“生成视频”。"
            />
            <div v-else-if="generating" class="videogen-progress">
              <div class="videogen-skeleton">
                <LoaderCircle class="animate-spin" />
                <p>视频生成约需 1~3 分钟，请稍候</p>
              </div>
            </div>
            <StatePanel
              v-else-if="currentJob.status === 4"
              kind="error"
              :title="currentJob.errorMessage ?? '视频生成失败'"
              :description="`错误代码：${currentJob.errorCode ?? 'UNKNOWN'}`"
            />
            <div v-else class="videogen-result">
              <video
                class="videogen-player"
                :src="currentJob.outputs[0]"
                controls
                playsinline
              ></video>
            </div>
          </div>
        </section>
      </div>

      <section class="card">
        <div class="card-header">
          <div>
            <h2>我的生成记录</h2>
            <span class="hint">按创建时间倒序展示</span>
          </div>
          <button
            class="btn btn-secondary"
            type="button"
            :disabled="historyLoading"
            @click="loadHistory()"
          >
            <RefreshCcw />刷新
          </button>
        </div>
        <StatePanel
          v-if="historyLoading && !jobs.length"
          kind="loading"
          title="生成记录加载中"
          description="正在读取历史生成任务。"
        /><StatePanel
          v-else-if="historyError && !jobs.length"
          kind="error"
          title="生成记录加载失败"
          :description="historyError"
          @retry="loadHistory()"
        /><StatePanel
          v-else-if="!jobs.length"
          kind="empty"
          title="暂无生成记录"
          description="生成的视频会保留在这里，可随时回放下载。"
        />
        <template v-else>
          <div v-if="historyError" class="form-error table-alert" role="alert">
            {{ historyError }}
          </div>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>描述词</th>
                  <th>档位</th>
                  <th>分辨率</th>
                  <th>时长</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th><span class="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody>
                <template v-for="job in jobs" :key="job.publicId">
                  <tr :class="{ 'row-failed': job.status === 4 }">
                    <td data-label="描述词">
                      <strong>{{ promptSummary(job.prompt) }}</strong>
                    </td>
                    <td data-label="档位">{{ tierLabel(job.tier) }}</td>
                    <td data-label="分辨率">{{ job.size.toUpperCase() }}</td>
                    <td data-label="时长">{{ job.durationSeconds }} 秒</td>
                    <td data-label="状态">
                      <StatusBadge
                        :label="status(job.status).label"
                        :tone="status(job.status).tone"
                      />
                    </td>
                    <td
                      data-label="创建时间"
                      :title="absoluteTime(job.createdAt)"
                    >
                      {{ absoluteTime(job.createdAt) }}
                    </td>
                    <td>
                      <div class="row-actions">
                        <button
                          v-if="job.status === 3"
                          class="btn btn-secondary btn-compact"
                          type="button"
                          @click="toggleExpand(job.publicId)"
                        >
                          <ChevronUp
                            v-if="expandedId === job.publicId"
                          /><ChevronDown v-else />{{
                            expandedId === job.publicId ? "收起" : "预览"
                          }}
                        </button>
                        <button
                          v-if="job.status === 3"
                          class="btn btn-secondary btn-compact"
                          type="button"
                          @click="saveVideo(job)"
                        >
                          <Download />下载
                        </button>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="expandedId === job.publicId && job.status === 3">
                    <td colspan="7">
                      <div class="videogen-result">
                        <video
                          class="videogen-player"
                          :src="job.outputs[0]"
                          controls
                          playsinline
                        ></video>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.videogen-workspace {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}
.videogen-form {
  display: grid;
  gap: 14px;
}
.videogen-actions {
  display: flex;
}
.videogen-actions .btn-block {
  width: 100%;
}
.videogen-stage-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.videogen-reference {
  position: relative;
  width: 120px;
  margin-top: 10px;
}
.videogen-reference img {
  width: 100%;
  display: block;
  border-radius: 8px;
  border: 1px solid var(--line);
}
.videogen-reference-remove {
  position: absolute;
  top: -7px;
  right: -7px;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  color: #fff;
  background: var(--color-text-faint);
  cursor: pointer;
}
.videogen-reference-remove svg {
  width: 13px;
  height: 13px;
}
.videogen-skeleton {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 240px;
  border-radius: 10px;
  border: 1px dashed var(--line);
  color: var(--muted);
  text-align: center;
}
.videogen-player {
  width: 100%;
  max-width: 640px;
  display: block;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: #000;
}
.upload-zone-active {
  border-color: var(--brand);
  background: var(--brand-soft);
}
@media (max-width: 1080px) {
  .videogen-workspace {
    grid-template-columns: 1fr;
  }
}
</style>

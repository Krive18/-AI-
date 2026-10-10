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

import ImageLightbox from "@/components/ImageLightbox.vue";
import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { ApiError } from "@/services/http";
import {
  createImageGeneration,
  downloadImage,
  getImageGeneration,
  listImageGenerations,
  type ImageGenerationJob,
  type ImageSize,
} from "@/services/imagegen";
import { useToastsStore } from "@/stores/toasts";
import { formatDateTime } from "@/utils/datetime";

const POLL_INTERVAL_MS = 2000;
const MAX_REFERENCES = 3;
const TERMINAL_STATUSES = new Set([3, 4]);

const toasts = useToastsStore();
const prompt = ref("");
const size = ref<ImageSize>("2K");
const count = ref(1);
const references = ref<Array<{ id: number; name: string; dataUrl: string }>>(
  [],
);
const dragging = ref(false);
const submitting = ref(false);
const currentJob = ref<ImageGenerationJob | null>(null);
const jobs = ref<ImageGenerationJob[]>([]);
const historyLoading = ref(true);
const historyError = ref("");
const expandedId = ref<string | null>(null);
const lightbox = ref<{ srcs: string[]; index: number } | null>(null);
let referenceSeq = 0;
let pollTimer: ReturnType<typeof setInterval> | undefined;

const generating = computed(
  () =>
    currentJob.value !== null &&
    !TERMINAL_STATUSES.has(currentJob.value.status),
);

const statuses: Record<
  number,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  1: { label: "排队中", tone: "neutral" },
  2: { label: "生成中", tone: "info" },
  3: { label: "已完成", tone: "success" },
  4: { label: "失败", tone: "danger" },
};
const sizeOptions: ImageSize[] = ["2K", "3K", "4K"];

function status(value: number) {
  return (
    statuses[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
function absoluteTime(value: string) {
  return formatDateTime(value);
}
function promptSummary(value: string) {
  return value.length > 30 ? `${value.slice(0, 30)}…` : value;
}
function addFiles(files: FileList | File[]) {
  for (const file of Array.from(files)) {
    if (references.value.length >= MAX_REFERENCES) {
      toasts.push("参考图最多上传 3 张", "error");
      break;
    }
    if (!file.type.startsWith("image/")) {
      toasts.push("参考图必须是图片文件", "error");
      continue;
    }
    const reader = new FileReader();
    reader.onload = () => {
      references.value.push({
        id: (referenceSeq += 1),
        name: file.name,
        dataUrl: String(reader.result),
      });
    };
    reader.readAsDataURL(file);
  }
}
function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files) addFiles(input.files);
  input.value = "";
}
function onDrop(event: DragEvent) {
  dragging.value = false;
  if (event.dataTransfer?.files) addFiles(event.dataTransfer.files);
}
function removeReference(id: number) {
  references.value = references.value.filter((item) => item.id !== id);
}
async function submit() {
  if (!prompt.value.trim()) {
    toasts.push("请填写图片描述", "error");
    return;
  }
  if (submitting.value) return;
  submitting.value = true;
  try {
    const result = await createImageGeneration({
      prompt: prompt.value.trim(),
      size: size.value,
      count: count.value,
      references: references.value.map((item) => item.dataUrl),
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
    const result = await getImageGeneration(currentJob.value.publicId);
    currentJob.value = result.job;
    if (TERMINAL_STATUSES.has(result.job.status)) {
      stopPolling();
      if (result.job.status === 3) {
        await loadHistory();
      }
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
    const page = await listImageGenerations(20);
    jobs.value = page.items;
  } catch (reason) {
    historyError.value =
      reason instanceof ApiError ? reason.message : "生成记录暂时无法加载。";
  } finally {
    historyLoading.value = false;
  }
}
async function saveImage(job: ImageGenerationJob, index: number) {
  try {
    const { blob, filename } = await downloadImage(job.publicId, index);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ?? `${job.publicId}-${index + 1}.png`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    toasts.push("图片下载失败，请稍后重试。", "error");
  }
}
async function saveAll(job: ImageGenerationJob) {
  for (let index = 0; index < job.outputs.length; index += 1) {
    await saveImage(job, index);
  }
}
function toggleExpand(publicId: string) {
  expandedId.value = expandedId.value === publicId ? null : publicId;
}

onMounted(() => void loadHistory());
onUnmounted(stopPolling);
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>图片生成</h1>
        <p>输入描述生成图片；上传参考图可改图或融合多图。</p>
      </div>
    </header>

    <div class="imagegen-workspace">
      <section class="card imagegen-panel">
        <div class="card-body">
          <form class="imagegen-form" @submit.prevent="submit">
            <div class="field">
              <label for="imagegen-prompt">描述词</label>
              <textarea
                id="imagegen-prompt"
                v-model="prompt"
                class="textarea"
                rows="5"
                maxlength="2000"
                placeholder="描述想要的画面，例如：一只在星空下打盹的橘猫，水彩风格"
              ></textarea>
              <span class="hint">{{ prompt.length }}/2000</span>
            </div>
            <div class="field">
              <label>参考图（可选）</label>
              <label
                class="upload-zone"
                :class="{ 'upload-zone-active': dragging }"
                for="imagegen-reference-file"
                @dragover.prevent="dragging = true"
                @dragleave.prevent="dragging = false"
                @drop.prevent="onDrop"
              >
                <ImagePlus aria-hidden="true" />
                <span>点击或拖拽上传，最多 3 张</span>
                <input
                  id="imagegen-reference-file"
                  type="file"
                  accept="image/*"
                  multiple
                  aria-label="上传参考图"
                  @change="onFileChange"
                />
              </label>
              <div v-if="references.length" class="imagegen-references">
                <div
                  v-for="item in references"
                  :key="item.id"
                  class="imagegen-reference"
                >
                  <img :src="item.dataUrl" :alt="item.name" />
                  <button
                    class="imagegen-reference-remove"
                    type="button"
                    :aria-label="`删除 ${item.name}`"
                    @click="removeReference(item.id)"
                  >
                    <X aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
            <div class="field">
              <label>生成张数</label>
              <div class="chip-group" role="group" aria-label="生成张数">
                <button
                  v-for="option in [1, 2, 3]"
                  :key="option"
                  class="chip"
                  :class="{ 'chip-active': count === option }"
                  type="button"
                  :aria-pressed="count === option"
                  @click="count = option"
                >
                  {{ option }} 张
                </button>
              </div>
            </div>
            <div class="field">
              <label>分辨率</label>
              <div class="chip-group" role="group" aria-label="分辨率">
                <button
                  v-for="option in sizeOptions"
                  :key="option"
                  class="chip"
                  :class="{ 'chip-active': size === option }"
                  type="button"
                  :aria-pressed="size === option"
                  @click="size = option"
                >
                  {{ option }}
                </button>
              </div>
            </div>
            <div class="imagegen-actions">
              <button
                class="btn btn-primary btn-block"
                type="submit"
                :disabled="submitting || generating"
              >
                <LoaderCircle v-if="submitting" class="animate-spin" />
                {{
                  generating ? "生成中…" : submitting ? "提交中…" : "生成图片"
                }}
              </button>
            </div>
          </form>
        </div>
      </section>

      <section class="card imagegen-stage">
        <div class="card-header">
          <div>
            <h2>生成结果</h2>
            <span v-if="currentJob" class="hint">{{
              promptSummary(currentJob.prompt)
            }}</span>
          </div>
          <div class="imagegen-stage-tools">
            <StatusBadge
              v-if="currentJob"
              :label="status(currentJob.status).label"
              :tone="status(currentJob.status).tone"
            />
            <button
              v-if="
                currentJob &&
                currentJob.status === 3 &&
                currentJob.outputs.length > 1
              "
              class="btn btn-secondary btn-compact"
              type="button"
              @click="saveAll(currentJob)"
            >
              <Download />全部下载
            </button>
          </div>
        </div>
        <div class="card-body">
          <StatePanel
            v-if="!currentJob"
            kind="empty"
            title="尚未生成图片"
            description="在左侧填写描述词，点击“生成图片”。"
          />
          <div v-else-if="generating" class="imagegen-results">
            <div
              v-for="index in currentJob.count"
              :key="index"
              class="imagegen-result"
            >
              <div class="imagegen-skeleton">
                <LoaderCircle class="animate-spin" />
              </div>
            </div>
          </div>
          <StatePanel
            v-else-if="currentJob.status === 4"
            kind="error"
            :title="currentJob.errorMessage ?? '图片生成失败'"
            :description="`错误代码：${currentJob.errorCode ?? 'UNKNOWN'}`"
          />
          <div v-else class="imagegen-results">
            <div
              v-for="(output, index) in currentJob.outputs"
              :key="output"
              class="imagegen-result"
            >
              <div class="imagegen-frame">
                <img
                  :src="output"
                  :alt="`${currentJob.prompt} ${index + 1}`"
                  title="点击放大预览"
                  @click="lightbox = { srcs: currentJob.outputs, index }"
                />
                <button
                  class="imagegen-download"
                  type="button"
                  :aria-label="`下载第 ${index + 1} 张`"
                  @click="saveImage(currentJob, index)"
                >
                  <Download />
                </button>
              </div>
            </div>
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
        description="生成的图片会保留在这里，可随时回下载。"
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
                <th>张数</th>
                <th>分辨率</th>
                <th>参考图</th>
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
                  <td data-label="张数">{{ job.count }}</td>
                  <td data-label="分辨率">{{ job.size }}</td>
                  <td data-label="参考图">{{ job.referenceCount }} 张</td>
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
                          expandedId === job.publicId ? "收起" : "下载"
                        }}
                      </button>
                    </div>
                  </td>
                </tr>
                <tr v-if="expandedId === job.publicId && job.status === 3">
                  <td colspan="7">
                    <div class="imagegen-results">
                      <div
                        v-for="(output, index) in job.outputs"
                        :key="output"
                        class="imagegen-result"
                      >
                        <div class="imagegen-frame">
                          <img
                            :src="output"
                            :alt="`${job.prompt} ${index + 1}`"
                            title="点击放大预览"
                            @click="lightbox = { srcs: job.outputs, index }"
                          />
                          <button
                            class="imagegen-download"
                            type="button"
                            :aria-label="`下载第 ${index + 1} 张`"
                            @click="saveImage(job, index)"
                          >
                            <Download />
                          </button>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>
    </section>
    <ImageLightbox
      v-if="lightbox"
      :srcs="lightbox.srcs"
      :index="lightbox.index"
      @close="lightbox = null"
    />
  </div>
</template>

<style scoped>
.imagegen-workspace {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}
.imagegen-form {
  display: grid;
  gap: 14px;
}
.imagegen-actions {
  display: flex;
}
.imagegen-actions .btn-block {
  width: 100%;
}
.imagegen-stage-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.imagegen-references {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}
.imagegen-reference {
  position: relative;
  width: 88px;
  height: 88px;
}
.imagegen-reference img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--line);
}
.imagegen-reference-remove {
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
.imagegen-reference-remove svg {
  width: 13px;
  height: 13px;
}
.imagegen-results {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.imagegen-result {
  display: grid;
  gap: 8px;
}
.imagegen-frame {
  position: relative;
}
.imagegen-frame img {
  width: 100%;
  display: block;
  border-radius: 10px;
  border: 1px solid var(--line);
  cursor: zoom-in;
}
.imagegen-download {
  position: absolute;
  right: 10px;
  bottom: 10px;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 10px;
  color: #fff;
  background: rgba(20, 26, 36, 0.78);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.imagegen-download svg {
  width: 17px;
  height: 17px;
}
.imagegen-frame:hover .imagegen-download,
.imagegen-download:focus-visible {
  opacity: 1;
}
.imagegen-skeleton {
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border-radius: 10px;
  border: 1px dashed var(--line);
  color: var(--muted);
}
.upload-zone-active {
  border-color: var(--brand);
  background: var(--brand-soft);
}
@media (max-width: 1080px) {
  .imagegen-workspace {
    grid-template-columns: 1fr;
  }
}
</style>

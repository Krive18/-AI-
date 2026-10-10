<script setup lang="ts">
import {
  Captions,
  FileVideo2,
  Languages,
  RadioTower,
  Sparkles,
  UploadCloud,
} from "@lucide/vue";
import {
  computed,
  nextTick,
  onMounted,
  reactive,
  ref,
  watch,
  type Ref,
} from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "@/services/http";
import {
  getTranslationOptions,
  type TranslationMode,
  uploadAndCreateProject,
} from "@/services/projects";
import { useToastsStore } from "@/stores/toasts";

const router = useRouter();
const toasts = useToastsStore();
const MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024;
const languages = [
  { code: "en-US", name: "英语", region: "美国" },
  { code: "ja-JP", name: "日语", region: "日本" },
  { code: "ko-KR", name: "韩语", region: "韩国" },
  { code: "vi-VN", name: "越南语", region: "越南" },
  { code: "ms-MY", name: "马来语", region: "马来西亚" },
  { code: "th-TH", name: "泰语", region: "泰国" },
  { code: "fil-PH", name: "菲律宾语", region: "菲律宾" },
  { code: "de-DE", name: "德语", region: "德国" },
  { code: "fr-FR", name: "法语", region: "法国" },
];
const selected = ref<string[]>(["en-US"]);
const translationMode = ref<TranslationMode>("professional");
const voiceGender = ref<"male" | "female">("male");
const VOICE_IDS: Record<"male" | "female", string> = {
  male: "audiobook_male_1",
  female: "audiobook_female_1",
};
const professionalProviderAvailable = ref(false);
const professionalSupportedLocales = ref<string[]>([]);
const youdaoProviderAvailable = ref(false);
const youdaoSupportedLocales = ref<string[]>([]);
// 字幕翻译模式下一版本开放;打开此开关即恢复显示
const subtitleModeEnabled = false;
const subtitleProviderAvailable = ref(false);
const subtitleSupportedLocales = ref<string[]>([]);
const optionsLoading = ref(true);
const youdaoLocaleUnsupported = computed(() =>
  selected.value.some(
    (locale) => !youdaoSupportedLocales.value.includes(locale),
  ),
);
const youdaoUnavailable = computed(
  () => !youdaoProviderAvailable.value || youdaoLocaleUnsupported.value,
);
const professionalUnavailable = computed(
  () =>
    !professionalProviderAvailable.value ||
    selected.value.some(
      (locale) => !professionalSupportedLocales.value.includes(locale),
    ),
);
const subtitleLocaleUnsupported = computed(() =>
  selected.value.some(
    (locale) => !subtitleSupportedLocales.value.includes(locale),
  ),
);
const subtitleUnavailable = computed(
  () => !subtitleProviderAvailable.value || subtitleLocaleUnsupported.value,
);
const file = ref<File | null>(null);
const fileError = ref("");
const dragOver = ref(false);
const dragDepth = ref(0);
const projectName = ref("");
const loading = ref(false);
const progress = ref(0);
const phase = ref("等待选择文件");
const error = ref("");
const attempt = ref<{ fingerprint: string; key: string } | null>(null);

const fieldKeys = ["upload", "projectName", "mode", "languages"] as const;
type FieldKey = (typeof fieldKeys)[number];
const fieldErrors = reactive<Record<FieldKey, string>>({
  upload: "",
  projectName: "",
  mode: "",
  languages: "",
});

const uploadCard = ref<HTMLElement | null>(null);
const modeCard = ref<HTMLElement | null>(null);
const languageCard = ref<HTMLElement | null>(null);
const errorSections: Array<[FieldKey, Ref<HTMLElement | null>]> = [
  ["upload", uploadCard],
  ["projectName", uploadCard],
  ["mode", modeCard],
  ["languages", languageCard],
];

const deliverySummary = computed(() =>
  selected.value.length
    ? `将生成 ${selected.value.length} 条配音成片、${selected.value.length} 个 SRT 字幕文件；成片不含烧录字幕。`
    : "请先选择目标语言。",
);

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value;
  let unit = "B";
  for (const next of units) {
    if (size < 1024) break;
    size /= 1024;
    unit = next;
  }
  return `${size.toFixed(1)} ${unit}`;
}

function supportedLocaleCodes(): string[] {
  const supported =
    translationMode.value === "professional"
      ? professionalSupportedLocales.value
      : translationMode.value === "youdao"
        ? youdaoSupportedLocales.value
        : subtitleSupportedLocales.value;
  return languages
    .filter((language) => supported.includes(language.code))
    .map((language) => language.code);
}

function selectAllLanguages() {
  selected.value = supportedLocaleCodes();
}

function clearLanguages() {
  selected.value = [];
}

watch(youdaoUnavailable, (unavailable) => {
  if (unavailable && translationMode.value === "youdao") {
    translationMode.value = "professional";
  }
});

watch(professionalUnavailable, (unavailable) => {
  if (
    unavailable &&
    translationMode.value === "professional" &&
    !youdaoUnavailable.value
  ) {
    translationMode.value = "youdao";
  }
});

watch(subtitleUnavailable, (unavailable) => {
  if (unavailable && translationMode.value === "subtitle") {
    translationMode.value = "professional";
  }
});

onMounted(async () => {
  try {
    const options = await getTranslationOptions();
    professionalProviderAvailable.value = options.modes.professional.available;
    professionalSupportedLocales.value =
      options.modes.professional.supportedLocales;
    youdaoProviderAvailable.value = options.modes.youdao.available;
    youdaoSupportedLocales.value = options.modes.youdao.supportedLocales;
    subtitleProviderAvailable.value = options.modes.subtitle.available;
    subtitleSupportedLocales.value = options.modes.subtitle.supportedLocales;
  } catch {
    professionalProviderAvailable.value = false;
    professionalSupportedLocales.value = [];
    youdaoProviderAvailable.value = false;
    youdaoSupportedLocales.value = [];
    subtitleProviderAvailable.value = false;
    subtitleSupportedLocales.value = [];
  } finally {
    optionsLoading.value = false;
  }
});

function pickFile(candidate: File | null | undefined) {
  fileError.value = "";
  if (!candidate) return;
  if (!/\.(mp4|mov|mkv)$/i.test(candidate.name)) {
    fileError.value = "仅支持 MP4、MOV 或 MKV 文件。";
    return;
  }
  if (candidate.size <= 0 || candidate.size > MAX_FILE_BYTES) {
    fileError.value = "视频大小必须在 2 GB 以内。";
    return;
  }
  file.value = candidate;
  error.value = "";
  attempt.value = null;
  progress.value = 0;
  projectName.value = candidate.name.replace(/\.[^.]+$/, "").slice(0, 128);
  phase.value = "文件已选择";
}

function selectFile(event: Event) {
  const input = event.target as HTMLInputElement;
  pickFile(input.files?.[0] ?? null);
  input.value = "";
}

function dragHasFiles(event: DragEvent): boolean {
  return !!event.dataTransfer?.types?.includes("Files");
}

function onDragEnter(event: DragEvent) {
  if (!dragHasFiles(event)) return;
  event.preventDefault();
  dragDepth.value += 1;
  dragOver.value = true;
}

function onDragOver(event: DragEvent) {
  if (dragHasFiles(event)) event.preventDefault();
}

function onDragLeave() {
  dragDepth.value = Math.max(0, dragDepth.value - 1);
  if (!dragDepth.value) dragOver.value = false;
}

function onDrop(event: DragEvent) {
  event.preventDefault();
  dragDepth.value = 0;
  dragOver.value = false;
  if (!dragHasFiles(event)) return;
  pickFile(event.dataTransfer?.files?.[0]);
}

function validateFields(): boolean {
  for (const key of fieldKeys) fieldErrors[key] = "";
  if (!file.value) {
    fieldErrors.upload = "请选择需要翻译的视频文件。";
  } else if (!/\.(mp4|mov|mkv)$/i.test(file.value.name)) {
    fieldErrors.upload = "仅支持 MP4、MOV 或 MKV 文件。";
  } else if (file.value.size <= 0 || file.value.size > MAX_FILE_BYTES) {
    fieldErrors.upload = "视频大小必须在 2 GB 以内。";
  }
  const name = projectName.value.trim();
  if (!name || name.length > 128) {
    fieldErrors.projectName = "项目名称需要填写，且不能超过 128 个字符。";
  }
  if (!selected.value.length) {
    fieldErrors.languages = "请至少选择一种目标语言。";
  }
  if (optionsLoading.value) {
    fieldErrors.mode = "正在检查翻译服务配置，请稍候。";
  } else if (
    (translationMode.value === "professional" &&
      professionalUnavailable.value) ||
    (translationMode.value === "youdao" && youdaoUnavailable.value) ||
    (translationMode.value === "subtitle" && subtitleUnavailable.value)
  ) {
    fieldErrors.mode = "当前翻译方式尚未配置或不支持所选语言。";
  }
  return fieldKeys.every((key) => !fieldErrors[key]);
}

function focusFirstError() {
  for (const [key, sectionRef] of errorSections) {
    const section = sectionRef.value;
    if (!fieldErrors[key] || !section) continue;
    section.scrollIntoView?.({ behavior: "smooth", block: "center" });
    const target = section.querySelector<HTMLElement>(
      "input:not([type=hidden]), button",
    );
    target?.focus();
    break;
  }
}

async function submit() {
  if (!validateFields()) {
    toasts.push("请检查表单中标红的项目", "error");
    await nextTick();
    focusFirstError();
    return;
  }
  const source = file.value as File;
  const name = projectName.value.trim();
  const fingerprint = `${source.name}:${source.size}:${source.lastModified}|${name}|${translationMode.value}|${voiceGender.value}|${[...selected.value].sort().join(",")}`;
  if (attempt.value?.fingerprint !== fingerprint)
    attempt.value = { fingerprint, key: globalThis.crypto.randomUUID() };
  loading.value = true;
  error.value = "";
  progress.value = 0;
  phase.value = "正在初始化上传";
  try {
    const project = await uploadAndCreateProject({
      file: source,
      name,
      targetLocales: [...selected.value],
      translationMode: translationMode.value,
      voiceId:
        translationMode.value === "professional" ||
        translationMode.value === "subtitle"
          ? VOICE_IDS[voiceGender.value]
          : undefined,
      idempotencyKey: attempt.value.key,
      onProgress(value) {
        progress.value = value;
        phase.value =
          value < 95
            ? "正在上传视频分片"
            : value < 100
              ? "正在创建翻译项目"
              : "项目创建完成";
      },
    });
    attempt.value = null;
    toasts.push("已创建翻译任务", "success");
    await router.push({
      name: "translation-detail",
      params: { projectId: project.publicId },
    });
  } catch (reason) {
    error.value =
      reason instanceof ApiError
        ? reason.message
        : reason instanceof Error
          ? reason.message
          : "项目创建失败，请稍后重试。";
    toasts.push(error.value, "error");
    phase.value = "上传未完成，可重新提交";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>新建视频翻译</h1>
        <p>
          上传中文视频并选择目标市场。系统会按语言创建独立子任务，完成配音视频与
          SRT 字幕。
        </p>
      </div>
    </header>
    <div v-if="error" class="form-error page-alert" role="alert">
      {{ error }}
    </div>
    <div class="translation-grid">
      <section
        ref="uploadCard"
        data-section="upload"
        class="card"
        :class="{
          'card-error': fieldErrors.upload || fieldErrors.projectName,
        }"
      >
        <div class="card-header">
          <h2>1. 上传源视频</h2>
          <span class="hint">MP4 / MOV / MKV，最大 2 GB</span>
        </div>
        <div class="card-body">
          <label
            class="upload-zone"
            :class="{ 'drag-over': dragOver }"
            for="video-file"
            @dragenter="onDragEnter"
            @dragover="onDragOver"
            @dragleave="onDragLeave"
            @drop="onDrop"
            ><UploadCloud aria-hidden="true" /><strong>{{
              file ? file.name : "选择中文视频"
            }}</strong
            ><span>{{
              file
                ? "重新选择或拖入可替换"
                : "点击选择或拖入视频文件，将分片上传到私有存储"
            }}</span
            ><input
              id="video-file"
              type="file"
              accept="video/mp4,video/quicktime,video/x-matroska,.mkv"
              :disabled="loading"
              @change="selectFile"
          /></label>
          <p v-if="fieldErrors.upload" class="field-error" role="alert">
            {{ fieldErrors.upload }}
          </p>
          <p v-if="fileError" class="field-error" role="alert">
            {{ fileError }}
          </p>
          <div v-if="file && !fileError" class="file-status">
            <span class="status-dot"></span
            ><span>{{ file.name }} · {{ formatBytes(file.size) }}</span
            ><span class="file-status-ok">校验通过</span>
          </div>
          <div v-if="file" class="field upload-name">
            <label for="project-name">项目名称</label
            ><input
              id="project-name"
              v-model="projectName"
              class="input"
              maxlength="128"
              :disabled="loading"
            />
            <p v-if="fieldErrors.projectName" class="field-error" role="alert">
              {{ fieldErrors.projectName }}
            </p>
          </div>
          <div
            v-if="loading || progress"
            class="upload-progress"
            role="progressbar"
            :aria-valuenow="progress"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <div class="progress large">
              <span :style="{ width: `${progress}%` }"></span>
            </div>
            <span>{{ phase }} · {{ progress }}%</span>
          </div>
        </div>
      </section>
      <section
        ref="modeCard"
        data-section="mode"
        class="card"
        :class="{ 'card-error': fieldErrors.mode }"
      >
        <div class="card-header">
          <h2>2. 选择翻译方式</h2>
          <span class="hint">专业精译为默认推荐</span>
        </div>
        <div class="card-body translation-mode-grid">
          <label
            class="translation-mode-option"
            :class="{ selected: translationMode === 'professional' }"
          >
            <input
              v-model="translationMode"
              name="translation-mode"
              type="radio"
              value="professional"
              :disabled="loading || optionsLoading || professionalUnavailable"
            />
            <span class="option-icon"><Sparkles aria-hidden="true" /></span>
            <span>
              <span class="mode-title"
                ><strong>专业精译</strong><em>推荐</em></span
              >
              <small>更适合正式发布，兼顾译文质量、字幕与配音效果。</small>
              <small
                v-if="!optionsLoading && professionalUnavailable"
                class="mode-warning"
                >专业精译供应商尚未配置或不支持所选语言。</small
              >
            </span>
          </label>
          <label
            class="translation-mode-option"
            :class="{
              selected: translationMode === 'youdao',
              disabled: youdaoUnavailable,
            }"
          >
            <input
              v-model="translationMode"
              name="translation-mode"
              type="radio"
              value="youdao"
              :disabled="loading || optionsLoading || youdaoUnavailable"
            />
            <span class="option-icon"><RadioTower aria-hidden="true" /></span>
            <span>
              <span class="mode-title"><strong>智能翻译</strong></span>
              <small>一体化完成识别、翻译与配音，适合快速交付。</small>
              <small v-if="optionsLoading" class="mode-warning"
                >正在检查服务配置…</small
              ><small v-else-if="!youdaoProviderAvailable" class="mode-warning"
                >管理员尚未配置智能翻译服务。</small
              ><small v-else-if="youdaoLocaleUnsupported" class="mode-warning"
                >智能翻译暂不支持所选语言，请使用专业精译。</small
              >
            </span>
          </label>
          <label
            v-if="subtitleModeEnabled"
            class="translation-mode-option"
            :class="{
              selected: translationMode === 'subtitle',
              disabled: subtitleUnavailable,
            }"
          >
            <input
              v-model="translationMode"
              name="translation-mode"
              type="radio"
              value="subtitle"
              :disabled="loading || optionsLoading || subtitleUnavailable"
            />
            <span class="option-icon"><Captions aria-hidden="true" /></span>
            <span>
              <span class="mode-title"><strong>字幕翻译</strong></span>
              <small
                >视频无口播、字幕在画面里时，自动识别字幕并翻译配音。</small
              >
              <small v-if="optionsLoading" class="mode-warning"
                >正在检查服务配置…</small
              ><small
                v-else-if="!subtitleProviderAvailable"
                class="mode-warning"
                >字幕翻译供应商尚未配置。</small
              ><small v-else-if="subtitleLocaleUnsupported" class="mode-warning"
                >字幕翻译暂不支持所选语言，请调整目标语言。</small
              >
            </span>
          </label>
          <div
            v-if="
              translationMode === 'professional' ||
              translationMode === 'subtitle'
            "
            class="voice-field"
          >
            <span class="voice-label">配音音色</span>
            <div class="chip-group" role="group" aria-label="配音音色">
              <button
                class="chip"
                :class="{ 'chip-active': voiceGender === 'male' }"
                type="button"
                :aria-pressed="voiceGender === 'male'"
                :disabled="loading"
                @click="voiceGender = 'male'"
              >
                男声
              </button>
              <button
                class="chip"
                :class="{ 'chip-active': voiceGender === 'female' }"
                type="button"
                :aria-pressed="voiceGender === 'female'"
                :disabled="loading"
                @click="voiceGender = 'female'"
              >
                女声
              </button>
            </div>
          </div>
          <p v-if="fieldErrors.mode" class="field-error" role="alert">
            {{ fieldErrors.mode }}
          </p>
        </div>
      </section>
      <section
        ref="languageCard"
        data-section="languages"
        class="card"
        :class="{ 'card-error': fieldErrors.languages }"
      >
        <div class="card-header">
          <h2>3. 选择目标语言</h2>
          <span class="language-tools"
            ><button
              class="link-button"
              type="button"
              :disabled="loading || optionsLoading"
              @click="selectAllLanguages"
            >
              全选</button
            ><button
              class="link-button"
              type="button"
              :disabled="loading"
              @click="clearLanguages"
            >
              清空
            </button></span
          >
        </div>
        <div class="card-body language-grid">
          <label
            v-for="language in languages"
            :key="language.code"
            class="language-option"
            :class="{ selected: selected.includes(language.code) }"
            ><input
              v-model="selected"
              type="checkbox"
              :value="language.code"
              :disabled="loading"
            /><span
              ><strong>{{ language.name }}</strong
              ><small>{{ language.region }} · {{ language.code }}</small
              ><small class="language-yield"
                >生成 1 条成片 + 1 个 SRT 字幕</small
              ></span
            ></label
          >
          <p v-if="fieldErrors.languages" class="field-error" role="alert">
            {{ fieldErrors.languages }}
          </p>
        </div>
      </section>
      <section class="card">
        <div class="card-header"><h2>4. 交付内容</h2></div>
        <div class="card-body">
          <p class="delivery-summary" data-testid="delivery-summary">
            {{ deliverySummary }}
          </p>
          <div class="delivery-list">
            <div>
              <span class="option-icon"><FileVideo2 /></span
              ><span
                ><strong>目标语言成片</strong
                ><small
                  >完成语音合成、时间轴对齐和视频导出后可下载。</small
                ></span
              >
            </div>
            <div>
              <span class="option-icon"><Captions /></span
              ><span
                ><strong>SRT 字幕</strong
                ><small>每个目标语言子任务都会生成独立字幕文件。</small></span
              >
            </div>
          </div>
        </div>
      </section>
      <aside class="card estimate-card">
        <div class="card-header"><h2>提交前确认</h2></div>
        <div class="card-body">
          <dl class="summary-list">
            <div>
              <dt>源文件</dt>
              <dd :title="file?.name ?? undefined">
                {{ file?.name ?? "尚未选择" }}
              </dd>
            </div>
            <div>
              <dt>目标语言</dt>
              <dd>{{ selected.length }} 种</dd>
            </div>
            <div>
              <dt>翻译方式</dt>
              <dd>
                {{
                  translationMode === "professional"
                    ? "专业精译"
                    : translationMode === "youdao"
                      ? "智能翻译"
                      : "字幕翻译"
                }}
              </dd>
            </div>
            <div>
              <dt>上传方式</dt>
              <dd>4 MB 顺序分片</dd>
            </div>
          </dl>
          <button
            class="btn btn-primary w-full"
            type="button"
            :disabled="loading"
            @click="submit"
          >
            <Languages />{{ loading ? `${progress}% 上传处理中` : "开始翻译" }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

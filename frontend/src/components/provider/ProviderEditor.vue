<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import type {
  ProviderCode,
  ProviderConfig,
  ProviderCreateInput,
  ProviderUpdateInput,
} from "@/services/adminOperations";

const props = defineProps<{
  mode: "create" | "edit";
  provider?: ProviderConfig | null;
  loading?: boolean;
}>();

const emit = defineEmits<{
  cancel: [];
  save: [payload: ProviderCreateInput | ProviderUpdateInput];
}>();

const presets: Array<{
  code: ProviderCode;
  label: string;
  capability: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  displayName: string;
  modelName: string;
  endpointUrl: string;
  timeoutMs?: number;
}> = [
  {
    code: "doubao_asr",
    label: "语音识别服务",
    capability: 1,
    displayName: "语音识别服务",
    modelName: "bigmodel",
    endpointUrl: "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
  },
  {
    code: "ark",
    label: "文本翻译服务",
    capability: 2,
    displayName: "文本翻译服务",
    modelName: "",
    endpointUrl: "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
  },
  {
    code: "minimax",
    label: "语音合成服务",
    capability: 3,
    displayName: "语音合成服务",
    modelName: "",
    endpointUrl: "",
  },
  {
    code: "youdao_si",
    label: "同声传译服务",
    capability: 4,
    displayName: "同声传译服务",
    modelName: "youdao-simultaneous-interpretation",
    endpointUrl: "wss://openapi.youdao.com/stream-audio/stream-si",
  },
  {
    code: "seedream",
    label: "图片生成服务",
    capability: 5,
    displayName: "图片生成服务",
    modelName: "doubao-seedream-5-0-260128",
    endpointUrl: "https://ark.cn-beijing.volces.com/api/v3/images/generations",
    timeoutMs: 120_000,
  },
  {
    code: "ark_vision",
    label: "字幕识别服务",
    capability: 6,
    displayName: "字幕识别服务",
    modelName: "doubao-seed-2-0-lite-260428",
    endpointUrl: "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    timeoutMs: 60_000,
  },
  {
    code: "seedance_video",
    label: "视频生成服务",
    capability: 7,
    displayName: "视频生成服务",
    modelName: "doubao-seedance-2-0-fast-260128",
    endpointUrl:
      "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
    timeoutMs: 30_000,
  },
];

const capabilityLabels: Record<number, string> = {
  1: "语音识别 ASR",
  2: "文本翻译",
  3: "语音合成 TTS",
  4: "一体化同声传译",
  5: "图片生成",
  6: "字幕识别",
  7: "视频生成",
};

function knownCode(value?: string): ProviderCode {
  return presets.some((preset) => preset.code === value)
    ? (value as ProviderCode)
    : "doubao_asr";
}

function initialForm() {
  const provider = props.provider;
  const selected =
    presets.find((item) => item.code === knownCode(provider?.providerCode)) ??
    presets[0];
  return {
    providerCode: selected.code,
    displayName: provider?.displayName ?? selected.displayName,
    priority: provider?.priority ?? 100,
    supportedLocales: provider?.supportedLocales?.join(", ") ?? "",
    modelName: provider?.modelName ?? selected.modelName,
    endpointUrl: provider?.endpointUrl ?? selected.endpointUrl,
    timeoutMs: provider ? 30_000 : (selected.timeoutMs ?? 30_000),
    apiKey: "",
    queryUrl:
      props.mode === "create" && selected.code === "doubao_asr"
        ? "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
        : "",
    resourceId:
      props.mode === "create" && selected.code === "doubao_asr"
        ? "volc.seedasr.auc"
        : "",
    pollUrl: "",
    downloadUrl: "",
    languageBoost: props.mode === "create" ? "auto" : "",
    defaultVoiceId: "",
    youdaoAppKey: "",
    youdaoTtsSex: "female",
    videoModelStandard:
      props.mode === "create" ? "doubao-seedance-2-0-260128" : "",
    videoModelFast:
      props.mode === "create" ? "doubao-seedance-2-0-fast-260128" : "",
    videoModelMini:
      props.mode === "create" ? "doubao-seedance-2-0-mini-260615" : "",
  };
}

const form = reactive(initialForm());
const validationError = ref("");
const preset = computed(
  () => presets.find((item) => item.code === form.providerCode) ?? presets[0],
);
const hasOptions = computed(
  () =>
    form.providerCode === "doubao_asr" ||
    form.providerCode === "minimax" ||
    form.providerCode === "youdao_si" ||
    form.providerCode === "seedance_video",
);
const integrationGuide = computed(() => {
  if (form.providerCode === "doubao_asr")
    return "语音识别服务：填写 API Key 即可；提交、查询地址和资源 ID 已按录音文件识别预填。";
  if (form.providerCode === "ark")
    return "文本翻译服务：填写模型名称和 API Key。";
  if (form.providerCode === "minimax")
    return "语音合成服务：填写模型名称、任务接口、默认音色和 API Key。";
  if (form.providerCode === "seedream")
    return "图片生成服务：填写模型名称和 API Key。";
  if (form.providerCode === "ark_vision")
    return "字幕识别服务：填写模型名称和 API Key，用于读出烧录在画面里的字幕。";
  if (form.providerCode === "seedance_video")
    return "视频生成服务：填写 API Key 即可；三个档位模型 ID 已按官方默认值预填，可在扩展配置中调整。";
  return "同声传译服务：填写应用 ID 与应用密钥；官方 WSS 地址已固定，单次完成识别、翻译与时间轴。";
});
const credentialLabel = "API Key";
const endpointLabel = computed(() =>
  form.providerCode === "youdao_si" ? "WSS 接口地址" : "HTTPS 接口地址",
);

watch(
  () => form.providerCode,
  (code) => {
    if (props.mode !== "create") return;
    const selected = presets.find((item) => item.code === code) ?? presets[0];
    form.displayName = selected.displayName;
    form.modelName = selected.modelName;
    form.endpointUrl = selected.endpointUrl;
    form.timeoutMs = selected.timeoutMs ?? 30_000;
    form.queryUrl =
      code === "doubao_asr"
        ? "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
        : "";
    form.resourceId = code === "doubao_asr" ? "volc.seedasr.auc" : "";
    form.pollUrl = "";
    form.downloadUrl = "";
    form.languageBoost = code === "minimax" ? "auto" : "";
    form.defaultVoiceId = "";
    form.youdaoAppKey = "";
    form.youdaoTtsSex = "female";
    form.videoModelStandard =
      code === "seedance_video" ? "doubao-seedance-2-0-260128" : "";
    form.videoModelFast =
      code === "seedance_video" ? "doubao-seedance-2-0-fast-260128" : "";
    form.videoModelMini =
      code === "seedance_video" ? "doubao-seedance-2-0-mini-260615" : "";
    form.supportedLocales =
      code === "youdao_si" ? "en-US, ja-JP, ko-KR, vi-VN, ms-MY, th-TH" : "";
  },
);

function parseLocales() {
  const values = form.supportedLocales
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return values.length ? values : null;
}

function optionsPayload(): Record<string, unknown> | undefined {
  if (form.providerCode === "doubao_asr") {
    const values = {
      query_url: form.queryUrl.trim(),
      resource_id: form.resourceId.trim(),
    };
    if (props.mode === "edit" && !Object.values(values).some(Boolean))
      return undefined;
    if (!values.query_url || !values.resource_id) {
      throw new Error("查询地址和资源 ID 必须完整填写。");
    }
    if (!values.query_url.startsWith("https://"))
      throw new Error("查询地址必须使用 HTTPS。");
    return values;
  }

  if (form.providerCode === "minimax") {
    const values = {
      poll_url: form.pollUrl.trim(),
      download_url: form.downloadUrl.trim(),
      language_boost: form.languageBoost.trim(),
      default_voice_id: form.defaultVoiceId.trim(),
    };
    if (props.mode === "edit" && !Object.values(values).some(Boolean))
      return undefined;
    if (
      !values.poll_url ||
      !values.download_url ||
      !values.language_boost ||
      !values.default_voice_id
    ) {
      throw new Error("轮询、下载地址、语言增强和默认音色必须完整填写。");
    }
    if (
      !values.poll_url.startsWith("https://") ||
      !values.download_url.startsWith("https://")
    ) {
      throw new Error("轮询和下载地址必须使用 HTTPS。");
    }
    return values;
  }
  if (form.providerCode === "youdao_si") {
    const values = {
      app_key: form.youdaoAppKey.trim(),
      tts_sex: form.youdaoTtsSex,
    };
    if (props.mode === "edit" && !values.app_key) return undefined;
    if (!values.app_key) throw new Error("应用 ID 必须填写。");
    if (!["female", "male"].includes(values.tts_sex))
      throw new Error("音色配置无效。");
    return values;
  }
  if (form.providerCode === "seedance_video") {
    const models = {
      standard: form.videoModelStandard.trim(),
      fast: form.videoModelFast.trim(),
      mini: form.videoModelMini.trim(),
    };
    if (props.mode === "edit" && !Object.values(models).some(Boolean))
      return undefined;
    if (!models.standard || !models.fast || !models.mini) {
      throw new Error("标准版、快速版、轻量版三个档位模型 ID 必须完整填写。");
    }
    return { models };
  }
  return undefined;
}

function submit() {
  validationError.value = "";
  try {
    const expectedScheme =
      form.providerCode === "youdao_si" ? "wss://" : "https://";
    if (!form.endpointUrl.startsWith(expectedScheme))
      throw new Error(
        form.providerCode === "youdao_si"
          ? "同声传译接口地址必须使用 WSS。"
          : "供应商接口地址必须使用 HTTPS。",
      );
    const options = optionsPayload();

    if (props.mode === "create") {
      const payload: ProviderCreateInput = {
        providerCode: form.providerCode,
        displayName: form.displayName.trim(),
        capability: preset.value.capability,
        priority: form.priority,
        supportedLocales: parseLocales(),
        modelName: form.modelName.trim(),
        endpointUrl: form.endpointUrl.trim(),
        timeoutMs: form.timeoutMs,
        apiKey: form.apiKey,
        ...(options ? { options } : {}),
      };
      emit("save", payload);
    } else if (props.provider) {
      const payload: ProviderUpdateInput = {
        displayName: form.displayName.trim(),
        priority: form.priority,
        supportedLocales: parseLocales() ?? [],
      };
      if (form.modelName.trim() !== props.provider.modelName)
        payload.modelName = form.modelName.trim();
      if (form.endpointUrl.trim() !== props.provider.endpointUrl)
        payload.endpointUrl = form.endpointUrl.trim();
      if (options) payload.options = options;
      if (form.apiKey) payload.apiKey = form.apiKey;
      emit("save", payload);
    }
    form.apiKey = "";
  } catch (reason) {
    validationError.value =
      reason instanceof Error ? reason.message : "请检查供应商配置。";
  }
}
</script>

<template>
  <section class="card provider-form-card">
    <div class="card-header">
      <div>
        <h2>
          {{
            mode === "create" ? "新增供应商" : `编辑 ${provider?.displayName}`
          }}
        </h2>
        <span class="hint">{{
          mode === "edit"
            ? "密钥与扩展配置留空即保持不变"
            : "密钥提交后不可查看"
        }}</span>
      </div>
    </div>
    <form class="card-body provider-form" @submit.prevent="submit">
      <div class="field">
        <label for="provider-code">供应商预设</label>
        <select
          id="provider-code"
          v-model="form.providerCode"
          class="select"
          :disabled="mode === 'edit'"
        >
          <option v-for="item in presets" :key="item.code" :value="item.code">
            {{ item.label }}
          </option>
        </select>
      </div>
      <div class="provider-integration-guide" role="note">
        <strong>接口接入位置</strong>
        <span>{{ integrationGuide }}</span>
      </div>
      <div class="field">
        <label>能力</label>
        <div class="readonly-value">
          {{ capabilityLabels[preset.capability] }}
        </div>
        <span class="hint">能力由供应商预设自动匹配。</span>
      </div>
      <div class="field">
        <label for="provider-name">显示名称</label>
        <input
          id="provider-name"
          v-model="form.displayName"
          class="input"
          required
          maxlength="128"
        />
      </div>
      <div class="field">
        <label for="provider-priority">优先级</label>
        <input
          id="provider-priority"
          v-model.number="form.priority"
          class="input"
          type="number"
          min="0"
          max="255"
          required
        />
      </div>
      <div class="field">
        <label for="provider-model">模型名称</label>
        <input
          id="provider-model"
          v-model="form.modelName"
          class="input"
          required
          maxlength="128"
        />
      </div>
      <div class="field">
        <label for="provider-endpoint">{{ endpointLabel }}</label>
        <input
          id="provider-endpoint"
          v-model="form.endpointUrl"
          class="input"
          type="url"
          required
        />
      </div>
      <div v-if="mode === 'create'" class="field">
        <label for="provider-timeout">请求超时（毫秒）</label>
        <input
          id="provider-timeout"
          v-model.number="form.timeoutMs"
          class="input"
          type="number"
          min="1"
          max="600000"
          required
        />
      </div>
      <div class="field">
        <label for="provider-locales">支持语言</label>
        <input
          id="provider-locales"
          v-model="form.supportedLocales"
          class="input"
          placeholder="en-US, ja-JP, ko-KR"
        />
        <span class="hint">使用英文逗号分隔；留空表示不限制。</span>
      </div>

      <fieldset v-if="hasOptions" class="options-panel">
        <legend>非敏感扩展配置</legend>
        <p class="hint">
          {{
            mode === "edit"
              ? "服务端不会回显现有值。全部留空会保留当前配置；修改时请完整填写。"
              : "这些参数会作为 options 保存，请勿填写任何密钥。"
          }}
        </p>
        <template v-if="form.providerCode === 'doubao_asr'">
          <div class="field">
            <label for="option-query-url">查询地址</label
            ><input
              id="option-query-url"
              v-model="form.queryUrl"
              class="input"
              type="url"
              placeholder="https://…"
            />
          </div>
          <div class="field">
            <label for="option-resource-id">资源 ID</label
            ><input
              id="option-resource-id"
              v-model="form.resourceId"
              class="input"
              placeholder="volc.seedasr.auc"
            />
          </div>
        </template>
        <template v-else-if="form.providerCode === 'minimax'">
          <div class="field">
            <label for="option-poll-url">轮询地址</label
            ><input
              id="option-poll-url"
              v-model="form.pollUrl"
              class="input"
              type="url"
              placeholder="https://…"
            />
          </div>
          <div class="field">
            <label for="option-download-url">下载地址</label
            ><input
              id="option-download-url"
              v-model="form.downloadUrl"
              class="input"
              type="url"
              placeholder="https://…"
            />
          </div>
          <div class="field">
            <label for="option-language-boost">语言增强</label
            ><input
              id="option-language-boost"
              v-model="form.languageBoost"
              class="input"
              placeholder="auto"
            />
          </div>
          <div class="field">
            <label for="option-default-voice">默认音色 ID</label
            ><input
              id="option-default-voice"
              v-model="form.defaultVoiceId"
              class="input"
              autocomplete="off"
            />
          </div>
        </template>
        <template v-else-if="form.providerCode === 'youdao_si'">
          <div class="field">
            <label for="option-app-key">应用 ID</label
            ><input
              id="option-app-key"
              v-model="form.youdaoAppKey"
              class="input"
              autocomplete="off"
              placeholder="控制台创建应用后获得"
            />
          </div>
          <div class="field">
            <label for="option-tts-sex">配音音色</label
            ><select
              id="option-tts-sex"
              v-model="form.youdaoTtsSex"
              class="select"
            >
              <option value="female">女声</option>
              <option value="male">男声</option>
            </select>
          </div>
        </template>
        <template v-else>
          <div class="field">
            <label for="option-video-model-standard">标准版模型 ID</label
            ><input
              id="option-video-model-standard"
              v-model="form.videoModelStandard"
              class="input"
              autocomplete="off"
            />
          </div>
          <div class="field">
            <label for="option-video-model-fast">快速版模型 ID</label
            ><input
              id="option-video-model-fast"
              v-model="form.videoModelFast"
              class="input"
              autocomplete="off"
            />
          </div>
          <div class="field">
            <label for="option-video-model-mini">轻量版模型 ID</label
            ><input
              id="option-video-model-mini"
              v-model="form.videoModelMini"
              class="input"
              autocomplete="off"
            />
          </div>
        </template>
      </fieldset>
      <div v-else class="options-panel options-panel-empty">
        <strong>扩展配置</strong>
        <span class="hint">此预设不需要额外 options。</span>
      </div>

      <div class="field provider-secret-field">
        <label for="provider-key">{{
          mode === "create" ? credentialLabel : `替换 ${credentialLabel}`
        }}</label>
        <input
          id="provider-key"
          v-model="form.apiKey"
          class="input"
          type="password"
          :required="mode === 'create'"
          autocomplete="new-password"
        />
        <span class="hint"
          >密钥仅通过专用字段提交，不会进入
          options、预填或写入浏览器存储。</span
        >
      </div>
      <div
        v-if="validationError"
        class="form-error provider-form-message"
        role="alert"
      >
        {{ validationError }}
      </div>
      <div class="provider-form-actions">
        <button class="btn btn-secondary" type="button" @click="emit('cancel')">
          取消
        </button>
        <button class="btn btn-primary" type="submit" :disabled="loading">
          {{ loading ? "正在保存…" : "保存配置" }}
        </button>
      </div>
    </form>
  </section>
</template>

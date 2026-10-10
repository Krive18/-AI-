<script setup lang="ts">
import {
  CheckCircle2,
  CircleDollarSign,
  History,
  RotateCcw,
  X,
} from "@lucide/vue";
import { computed, onMounted, reactive, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  activateProvider,
  createProviderPrice,
  listProviderPrices,
  listProviderVersions,
  type ProviderConfig,
  type ProviderPrice,
  type ProviderPriceCreateInput,
  type ProviderVersion,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";

const props = defineProps<{ provider: ProviderConfig }>();
const emit = defineEmits<{
  close: [];
  activated: [provider: ProviderConfig];
}>();

const versions = ref<ProviderVersion[]>([]);
const prices = ref<ProviderPrice[]>([]);
const nextCursor = ref<number | null>(null);
const loading = ref(true);
const priceLoading = ref(false);
const actionLoading = ref("");
const error = ref("");
const notice = ref("");

type BillingUnit = ProviderPrice["billingUnit"];
const priceForm = reactive({
  versionId: "",
  locale: "",
  billingUnit: "seconds" as BillingUnit,
  unitSize: 1,
  priceMode: "cny" as "cny" | "microunit",
  priceValue: 0.01,
  effectiveFrom: localDateTime(),
  effectiveTo: "",
});

const unitLabels: Record<BillingUnit, string> = {
  characters: "字符",
  tokens: "Token",
  milliseconds: "毫秒",
  seconds: "秒",
};

const versionNumbers = computed(
  () =>
    new Map(
      versions.value.map((version) => [version.publicId, version.versionNo]),
    ),
);

function localDateTime() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function friendly(reason: unknown) {
  return reason instanceof ApiError ? reason.message : "供应商版本请求未完成。";
}

function date(value: string | null) {
  if (!value) return "长期有效";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function money(microunit: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  }).format(microunit / 1_000_000);
}

async function loadPrices() {
  if (!versions.value.length) {
    prices.value = [];
    return;
  }
  priceLoading.value = true;
  try {
    const responses = await Promise.all(
      versions.value.map((version) => listProviderPrices(version.publicId)),
    );
    prices.value = responses.flatMap((response) => response.items);
  } finally {
    priceLoading.value = false;
  }
}

async function load(cursor?: number) {
  loading.value = true;
  error.value = "";
  try {
    const result = await listProviderVersions(props.provider.publicId, cursor);
    versions.value = cursor
      ? [...versions.value, ...result.items]
      : result.items;
    nextCursor.value = result.nextCursor;
    if (!priceForm.versionId && versions.value.length)
      priceForm.versionId =
        props.provider.activeVersionId ?? versions.value[0].publicId;
    await loadPrices();
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    loading.value = false;
  }
}

async function activate(version: ProviderVersion) {
  actionLoading.value = `activate-${version.publicId}`;
  error.value = "";
  notice.value = "";
  try {
    const result = await activateProvider(props.provider, version.publicId);
    emit("activated", result.provider);
    notice.value = `版本 V${version.versionNo} 已激活。`;
  } catch (reason) {
    error.value = friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}

function microunitValue() {
  if (!Number.isFinite(priceForm.priceValue) || priceForm.priceValue < 0)
    throw new Error("单价必须是大于或等于 0 的数字。");
  const value =
    priceForm.priceMode === "cny"
      ? Math.round(priceForm.priceValue * 1_000_000)
      : priceForm.priceValue;
  if (!Number.isInteger(value)) throw new Error("微元单价必须填写整数。");
  return value;
}

async function createPrice() {
  error.value = "";
  notice.value = "";
  try {
    if (!priceForm.versionId) throw new Error("请选择计费版本。");
    if (!Number.isInteger(priceForm.unitSize) || priceForm.unitSize <= 0)
      throw new Error("计费单位数量必须是正整数。");
    const from = new Date(priceForm.effectiveFrom);
    const to = priceForm.effectiveTo ? new Date(priceForm.effectiveTo) : null;
    if (Number.isNaN(from.getTime())) throw new Error("请选择生效时间。");
    if (to && (Number.isNaN(to.getTime()) || to <= from))
      throw new Error("失效时间必须晚于生效时间。");

    const input: ProviderPriceCreateInput = {
      versionId: priceForm.versionId,
      capability: props.provider.capability,
      locale: priceForm.locale.trim() || null,
      billingUnit: priceForm.billingUnit,
      unitSize: priceForm.unitSize,
      unitPriceMicrounit: microunitValue(),
      currency: "CNY",
      effectiveFrom: from.toISOString(),
      effectiveTo: to?.toISOString() ?? null,
    };
    actionLoading.value = "price";
    await createProviderPrice(input);
    await loadPrices();
    notice.value = "价格规则已新增。";
    priceForm.locale = "";
    priceForm.effectiveFrom = localDateTime();
    priceForm.effectiveTo = "";
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : friendly(reason);
  } finally {
    actionLoading.value = "";
  }
}

onMounted(() => load());
</script>

<template>
  <section
    class="card provider-history"
    aria-labelledby="provider-history-title"
  >
    <div class="card-header provider-history-header">
      <div>
        <h2 id="provider-history-title">
          <History />{{ provider.displayName }}：版本与价格
        </h2>
        <span class="hint">历史配置只读；激活旧版本不会回显任何密钥。</span>
      </div>
      <button
        class="icon-button"
        type="button"
        aria-label="关闭版本与价格面板"
        @click="emit('close')"
      >
        <X />
      </button>
    </div>
    <div v-if="error" class="form-error page-alert" role="alert">
      {{ error }}
    </div>
    <div v-if="notice" class="success-note page-alert" role="status">
      {{ notice }}
    </div>

    <StatePanel
      v-if="loading && !versions.length"
      kind="loading"
      title="正在加载版本"
      description="读取历史配置与计费规则。"
    />
    <StatePanel
      v-else-if="!versions.length"
      kind="empty"
      title="还没有配置版本"
      description="创建或更新模型配置后会生成不可变版本。"
    />
    <template v-else>
      <div class="version-list">
        <article
          v-for="version in versions"
          :key="version.publicId"
          class="version-row"
        >
          <div class="version-number">V{{ version.versionNo }}</div>
          <div>
            <div class="heading-line">
              <strong>{{ version.modelName }}</strong>
              <StatusBadge
                v-if="version.publicId === provider.activeVersionId"
                label="当前生效"
                tone="success"
              />
            </div>
            <div class="cell-note">
              {{ version.endpointUrl }} · {{ version.timeoutMs }} ms
            </div>
            <div class="cell-note">
              {{ date(version.createdAt) }} · 密钥{{
                version.hasKey ? "已安全配置" : "未配置"
              }}
            </div>
          </div>
          <button
            v-if="version.publicId !== provider.activeVersionId"
            class="btn btn-secondary"
            type="button"
            :disabled="actionLoading === `activate-${version.publicId}`"
            @click="activate(version)"
          >
            <RotateCcw />{{
              actionLoading === `activate-${version.publicId}`
                ? "激活中…"
                : "激活此版本"
            }}
          </button>
          <span v-else class="active-version-note"
            ><CheckCircle2 />正在使用</span
          >
        </article>
      </div>
      <div v-if="nextCursor" class="load-more">
        <button
          class="btn btn-secondary"
          type="button"
          :disabled="loading"
          @click="load(nextCursor ?? undefined)"
        >
          {{ loading ? "加载中…" : "加载更多版本" }}
        </button>
      </div>

      <div class="provider-price-section">
        <div class="section-heading">
          <div>
            <h3><CircleDollarSign />价格规则</h3>
            <p>
              规则绑定具体版本，费用统一按人民币微元落库（1 CNY = 1,000,000
              微元）。
            </p>
          </div>
        </div>
        <form class="price-form" @submit.prevent="createPrice">
          <div class="field">
            <label for="price-version">计费版本</label
            ><select
              id="price-version"
              v-model="priceForm.versionId"
              class="select"
              required
            >
              <option
                v-for="version in versions"
                :key="version.publicId"
                :value="version.publicId"
              >
                V{{ version.versionNo }} · {{ version.modelName }}
              </option>
            </select>
          </div>
          <div class="field">
            <label for="price-unit">计费单位</label
            ><select
              id="price-unit"
              v-model="priceForm.billingUnit"
              class="select"
            >
              <option value="characters">字符 characters</option>
              <option value="tokens">Token tokens</option>
              <option value="milliseconds">毫秒 milliseconds</option>
              <option value="seconds">秒 seconds</option>
            </select>
          </div>
          <div class="field">
            <label for="price-unit-size">每档单位数量</label
            ><input
              id="price-unit-size"
              v-model.number="priceForm.unitSize"
              class="input"
              type="number"
              min="1"
              step="1"
              required
            />
          </div>
          <div class="field">
            <label for="price-mode">单价输入单位</label
            ><select
              id="price-mode"
              v-model="priceForm.priceMode"
              class="select"
            >
              <option value="cny">人民币 CNY</option>
              <option value="microunit">人民币微元</option>
            </select>
          </div>
          <div class="field">
            <label for="price-value">单价</label
            ><input
              id="price-value"
              v-model.number="priceForm.priceValue"
              class="input"
              type="number"
              min="0"
              :step="priceForm.priceMode === 'cny' ? '0.000001' : '1'"
              required
            /><span class="hint"
              >每 {{ priceForm.unitSize }}
              {{ unitLabels[priceForm.billingUnit] }}的价格</span
            >
          </div>
          <div class="field">
            <label for="price-locale">适用语言（可选）</label
            ><input
              id="price-locale"
              v-model="priceForm.locale"
              class="input"
              placeholder="如 ja-JP"
            />
          </div>
          <div class="field">
            <label for="price-from">生效时间</label
            ><input
              id="price-from"
              v-model="priceForm.effectiveFrom"
              class="input"
              type="datetime-local"
              required
            />
          </div>
          <div class="field">
            <label for="price-to">失效时间（可选）</label
            ><input
              id="price-to"
              v-model="priceForm.effectiveTo"
              class="input"
              type="datetime-local"
            />
          </div>
          <div class="price-form-actions">
            <button
              class="btn btn-primary"
              type="submit"
              :disabled="actionLoading === 'price'"
            >
              {{ actionLoading === "price" ? "正在新增…" : "新增价格规则" }}
            </button>
          </div>
        </form>

        <StatePanel
          v-if="priceLoading"
          kind="loading"
          title="正在读取价格规则"
          description="正在按已加载版本汇总价格。"
        />
        <StatePanel
          v-else-if="!prices.length"
          kind="empty"
          title="暂无价格规则"
          description="添加第一条规则后，调用费用会按版本和生效期匹配。"
        />
        <div v-else class="table-wrap">
          <table class="data-table price-table">
            <thead>
              <tr>
                <th>版本 / 模型</th>
                <th>语言</th>
                <th>计费档位</th>
                <th>单价</th>
                <th>生效期</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="price in prices" :key="price.publicId">
                <td data-label="版本 / 模型">
                  <strong
                    >V{{
                      price.versionId
                        ? (versionNumbers.get(price.versionId) ?? "—")
                        : "通用"
                    }}</strong
                  >
                  <div class="cell-note">{{ price.modelName }}</div>
                </td>
                <td data-label="语言">{{ price.locale ?? "全部语言" }}</td>
                <td data-label="计费档位">
                  每 {{ price.unitSize }} {{ unitLabels[price.billingUnit] }}
                </td>
                <td data-label="单价">
                  <strong>{{ money(price.unitPriceMicrounit) }}</strong>
                  <div class="cell-note">
                    {{ price.unitPriceMicrounit.toLocaleString("zh-CN") }} 微元
                  </div>
                </td>
                <td data-label="生效期">
                  {{ date(price.effectiveFrom) }}
                  <div class="cell-note">至 {{ date(price.effectiveTo) }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

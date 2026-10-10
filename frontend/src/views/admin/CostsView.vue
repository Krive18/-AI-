<script setup lang="ts">
import {
  CircleDollarSign,
  Coins,
  Download,
  Filter,
  TrendingUp,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  exportCostRecords,
  getCostSummary,
  listCostRecords,
  type CostRecord,
  type CostSummaryItem,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";
import { formatDateTime } from "@/utils/datetime";

function localDate(date: Date) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}
const now = new Date();
const tomorrow = new Date(now);
tomorrow.setDate(tomorrow.getDate() + 1);
const startDate = ref(
  localDate(new Date(now.getFullYear(), now.getMonth(), 1)),
);
const endDate = ref(localDate(tomorrow));
const capability = ref("");
const language = ref("");
const model = ref("");
const summary = ref<CostSummaryItem[]>([]);
const records = ref<CostRecord[]>([]);
const nextCursor = ref<number | null>(null);
const loading = ref(true);
const error = ref("");
const capabilityLabels: Record<number, string> = {
  1: "语音识别 ASR",
  2: "文本翻译",
  3: "语音合成 TTS",
  4: "一体化同声传译",
  5: "图片生成",
  6: "字幕识别",
  7: "视频生成",
};
const totalCost = computed(() =>
  summary.value.reduce((sum, item) => sum + item.costMicrounit, 0),
);
const requestCount = computed(() =>
  summary.value.reduce((sum, item) => sum + item.requestCount, 0),
);
const totalUnits = computed(() =>
  summary.value.reduce(
    (sum, item) => sum + item.inputUnits + item.outputUnits,
    0,
  ),
);

function filters() {
  return {
    start: startDate.value ? `${startDate.value}T00:00:00` : undefined,
    end: endDate.value ? `${endDate.value}T00:00:00` : undefined,
    capability: capability.value ? Number(capability.value) : undefined,
    language: language.value || undefined,
    model: model.value.trim() || undefined,
  };
}
function money(value: number) {
  return `¥${(value / 1_000_000).toFixed(4)}`;
}
function number(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}
function date(value: string) {
  return formatDateTime(value);
}
async function load() {
  error.value = "";
  if (startDate.value && endDate.value && startDate.value >= endDate.value) {
    loading.value = false;
    error.value = "结束日期必须晚于开始日期。";
    return;
  }
  loading.value = true;
  try {
    const [grouped, page] = await Promise.all([
      getCostSummary(filters()),
      listCostRecords(filters()),
    ]);
    summary.value = grouped.items;
    records.value = page.items;
    nextCursor.value = page.nextCursor;
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "费用数据暂时无法加载。";
  } finally {
    loading.value = false;
  }
}
async function loadMore() {
  if (!nextCursor.value) return;
  loading.value = true;
  error.value = "";
  try {
    const page = await listCostRecords(filters(), nextCursor.value);
    records.value.push(...page.items);
    nextCursor.value = page.nextCursor;
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "费用明细加载失败。";
  } finally {
    loading.value = false;
  }
}
async function exportCsv() {
  loading.value = true;
  error.value = "";
  try {
    const result = await exportCostRecords(filters());
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.filename ?? "ai-usage-records.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "费用明细导出失败。";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>调用费用</h1>
        <p>
          按日期、能力、语言与模型核对真实计费记录。结束日期为不包含当日的统计边界。
        </p>
      </div>
      <button
        class="btn btn-secondary"
        type="button"
        :disabled="loading"
        @click="exportCsv"
      >
        <Download />导出最近 200 条 CSV
      </button>
    </header>
    <section class="card cost-filters">
      <form class="card-body filter-bar" @submit.prevent="load">
        <div class="field">
          <label for="cost-start">开始日期</label
          ><input
            id="cost-start"
            v-model="startDate"
            class="input"
            type="date"
          />
        </div>
        <div class="field">
          <label for="cost-end">结束日期（不含）</label
          ><input id="cost-end" v-model="endDate" class="input" type="date" />
        </div>
        <div class="field">
          <label for="cost-capability">能力</label
          ><select id="cost-capability" v-model="capability" class="select">
            <option value="">全部能力</option>
            <option value="1">ASR</option>
            <option value="2">文本翻译</option>
            <option value="3">TTS</option>
            <option value="4">一体化同声传译</option>
            <option value="5">图片生成</option>
          </select>
        </div>
        <div class="field">
          <label for="cost-language">语言</label
          ><input
            id="cost-language"
            v-model="language"
            class="input"
            placeholder="如 ja-JP"
          />
        </div>
        <div class="field">
          <label for="cost-model">模型</label
          ><input
            id="cost-model"
            v-model="model"
            class="input"
            placeholder="精确模型名称"
          />
        </div>
        <button
          class="btn btn-secondary filter-submit"
          type="submit"
          :disabled="loading"
        >
          <Filter />应用筛选
        </button>
      </form>
    </section>
    <StatePanel
      v-if="loading && !records.length"
      kind="loading"
      title="正在汇总费用"
      description="正在读取计费汇总和调用明细。"
    /><StatePanel
      v-else-if="error && !records.length"
      kind="error"
      title="费用加载失败"
      :description="error"
      @retry="load"
    /><template v-else>
      <div v-if="error" class="form-error page-alert" role="alert">
        {{ error }}
      </div>
      <div class="grid-3">
        <article class="card stat">
          <CircleDollarSign class="stat-icon" />
          <div class="stat-label">筛选区间费用</div>
          <div class="stat-value">{{ money(totalCost) }}</div>
          <div class="stat-note">以计费快照为准</div>
        </article>
        <article class="card stat">
          <Coins class="stat-icon" />
          <div class="stat-label">调用次数</div>
          <div class="stat-value">{{ number(requestCount) }}</div>
          <div class="stat-note">包含成功与失败记录</div>
        </article>
        <article class="card stat">
          <TrendingUp class="stat-icon" />
          <div class="stat-label">输入输出单位</div>
          <div class="stat-value">{{ number(totalUnits) }}</div>
          <div class="stat-note">各能力原始计费量合计</div>
        </article>
      </div>
      <section class="card detail-section">
        <div class="card-header">
          <h2>费用明细</h2>
          <span class="hint">共加载 {{ records.length }} 条</span>
        </div>
        <StatePanel
          v-if="!records.length"
          kind="empty"
          title="当前筛选无费用记录"
          description="调整日期或筛选条件后重新查询。"
        />
        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间 / 记录</th>
                <th>能力 / 模型</th>
                <th>项目 / 语言</th>
                <th>计费量</th>
                <th>状态</th>
                <th>金额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in records" :key="row.publicId">
                <td data-label="时间 / 记录">
                  {{ date(row.createdAt) }}
                  <div class="cell-note">{{ row.publicId }}</div>
                </td>
                <td data-label="能力 / 模型">
                  <strong>{{
                    capabilityLabels[row.capability] ?? `能力 ${row.capability}`
                  }}</strong>
                  <div class="cell-note">{{ row.model }}</div>
                </td>
                <td data-label="项目 / 语言">
                  #{{ row.projectId }} · {{ row.language ?? "无目标语言" }}
                </td>
                <td data-label="计费量">
                  {{ number(row.inputUnits) }} / {{ number(row.outputUnits) }}
                </td>
                <td data-label="状态">
                  <StatusBadge
                    :label="
                      row.status === 1
                        ? '成功'
                        : row.status === 2
                          ? '失败'
                          : '已取消'
                    "
                    :tone="
                      row.status === 1
                        ? 'success'
                        : row.status === 2
                          ? 'danger'
                          : 'neutral'
                    "
                  />
                </td>
                <td data-label="金额">
                  <strong>{{ money(row.costMicrounit) }}</strong>
                  <div v-if="row.errorCode" class="cell-note error-text">
                    {{ row.errorCode }}
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
            @click="loadMore"
          >
            {{ loading ? "加载中…" : "加载更多" }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

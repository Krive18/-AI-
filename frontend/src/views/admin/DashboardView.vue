<script setup lang="ts">
import { Activity, CircleDollarSign, Clock3, ListVideo } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  getDashboard,
  listAdminTasks,
  type AdminTask,
  type DashboardSummary,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";
import { formatDateTime } from "@/utils/datetime";

const summary = ref<DashboardSummary | null>(null);
const tasks = ref<AdminTask[]>([]);
const loading = ref(true);
const error = ref("");
const successPercent = computed(
  () => `${((summary.value?.successRate ?? 0) * 100).toFixed(1)}%`,
);
const statusLabels: Record<
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

function money(value: number) {
  return `¥${(value / 1_000_000).toFixed(2)}`;
}
function formatDate(value: string) {
  return formatDateTime(value);
}
function status(value: number) {
  return (
    statusLabels[value] ?? { label: `状态 ${value}`, tone: "neutral" as const }
  );
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [dashboard, latest] = await Promise.all([
      getDashboard(),
      listAdminTasks({ limit: 5 }),
    ]);
    summary.value = dashboard;
    tasks.value = latest.items;
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "运行概览暂时无法加载。";
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
        <h1>运行概览</h1>
        <p>集中查看累计项目、当前队列、供应商可用数量与实际调用费用。</p>
      </div>
    </header>
    <StatePanel
      v-if="loading"
      kind="loading"
      title="正在加载运行数据"
      description="正在汇总任务和费用信息。"
    />
    <StatePanel
      v-else-if="error"
      kind="error"
      title="运行概览加载失败"
      :description="error"
      @retry="load"
    />
    <template v-else-if="summary">
      <div class="grid-4">
        <article class="card stat">
          <ListVideo class="stat-icon" />
          <div class="stat-label">累计项目</div>
          <div class="stat-value">{{ summary.projectCount }}</div>
          <div class="stat-note">成功率 {{ successPercent }}</div>
        </article>
        <article class="card stat">
          <Activity class="stat-icon" />
          <div class="stat-label">当前队列</div>
          <div class="stat-value">{{ summary.queueBacklog }}</div>
          <div class="stat-note">等待或正在处理</div>
        </article>
        <article class="card stat">
          <Clock3 class="stat-icon" />
          <div class="stat-label">累计视频时长</div>
          <div class="stat-value">{{ summary.videoMinutes }}m</div>
          <div class="stat-note">已入库源视频</div>
        </article>
        <article class="card stat">
          <CircleDollarSign class="stat-icon" />
          <div class="stat-label">今日调用费用</div>
          <div class="stat-value">{{ money(summary.todayCostMicrounit) }}</div>
          <div class="stat-note">
            本月 {{ money(summary.monthCostMicrounit) }}
          </div>
        </article>
      </div>
      <div class="dashboard-grid">
        <section class="card">
          <div class="card-header">
            <h2>最新任务</h2>
            <RouterLink class="table-link" to="/admin/tasks"
              >查看全部</RouterLink
            >
          </div>
          <StatePanel
            v-if="!tasks.length"
            kind="empty"
            title="暂无翻译任务"
            description="创建业务任务后，最新进度会显示在这里。"
          />
          <div v-else class="compact-list">
            <div v-for="task in tasks" :key="task.publicId" class="compact-row">
              <div>
                <strong>{{ task.publicId }}</strong
                ><span
                  >{{ task.language }} · {{ formatDate(task.updatedAt) }}</span
                >
              </div>
              <StatusBadge
                :label="status(task.status).label"
                :tone="status(task.status).tone"
              />
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-header">
            <h2>供应商状态</h2>
            <span class="hint">实时配置数据</span>
          </div>
          <div class="health-list">
            <div>
              <span
                ><i
                  class="health-dot"
                  :class="summary.providerStatus.enabled ? 'good' : 'warn'"
                ></i
                >已启用供应商</span
              ><strong>{{ summary.providerStatus.enabled }} 个</strong>
            </div>
            <div>
              <span
                ><i
                  class="health-dot"
                  :class="summary.queueBacklog ? 'warn' : 'good'"
                ></i
                >任务队列</span
              ><strong>{{
                summary.queueBacklog
                  ? `${summary.queueBacklog} 个待处理`
                  : "无积压"
              }}</strong>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

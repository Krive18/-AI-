<script setup lang="ts">
import { Filter } from "@lucide/vue";
import { onMounted, ref } from "vue";

import StatePanel from "@/components/StatePanel.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import {
  listAuditLogs,
  listProviderCalls,
  listTaskLogs,
  type AuditLogEntry,
  type ProviderCallEntry,
  type TaskLogEntry,
} from "@/services/adminOperations";
import { ApiError } from "@/services/http";
import { formatDateTime } from "@/utils/datetime";

type LogKind = "audit" | "tasks" | "provider";
const kind = ref<LogKind>("audit");
const audits = ref<AuditLogEntry[]>([]);
const taskEvents = ref<TaskLogEntry[]>([]);
const providerCalls = ref<ProviderCallEntry[]>([]);
const filter = ref("");
const nextCursor = ref<number | null>(null);
const loading = ref(true);
const error = ref("");
const capabilityLabels: Record<number, string> = {
  1: "ASR",
  2: "文本翻译",
  3: "TTS",
  4: "一体化同声传译",
  5: "图片生成",
  6: "字幕识别",
  7: "视频生成",
};

function date(value: string) {
  return formatDateTime(value);
}
function money(value: number) {
  return `¥${(value / 1_000_000).toFixed(4)}`;
}
function currentLength() {
  return kind.value === "audit"
    ? audits.value.length
    : kind.value === "tasks"
      ? taskEvents.value.length
      : providerCalls.value.length;
}
async function load(cursor?: number) {
  loading.value = true;
  error.value = "";
  try {
    if (kind.value === "audit") {
      const page = await listAuditLogs({
        cursor,
        action: filter.value.trim() || undefined,
      });
      audits.value = cursor ? [...audits.value, ...page.items] : page.items;
      nextCursor.value = page.nextCursor;
    } else if (kind.value === "tasks") {
      const numeric = filter.value ? Number(filter.value) : undefined;
      const page = await listTaskLogs({
        cursor,
        projectId: Number.isFinite(numeric) ? numeric : undefined,
      });
      taskEvents.value = cursor
        ? [...taskEvents.value, ...page.items]
        : page.items;
      nextCursor.value = page.nextCursor;
    } else {
      const page = await listProviderCalls({
        cursor,
        model: filter.value.trim() || undefined,
      });
      providerCalls.value = cursor
        ? [...providerCalls.value, ...page.items]
        : page.items;
      nextCursor.value = page.nextCursor;
    }
  } catch (reason) {
    error.value =
      reason instanceof ApiError ? reason.message : "日志数据暂时无法加载。";
  } finally {
    loading.value = false;
  }
}
function choose(value: LogKind) {
  kind.value = value;
  filter.value = "";
  nextCursor.value = null;
  void load();
}
onMounted(() => load());
</script>

<template>
  <div class="page">
    <header class="page-heading">
      <div>
        <h1>系统日志</h1>
        <p>只读查看管理审计、任务事件和供应商调用记录；系统不提供删除入口。</p>
      </div>
    </header>
    <section class="card">
      <div class="log-tabs" role="tablist" aria-label="日志类型">
        <button
          :class="{ active: kind === 'audit' }"
          role="tab"
          type="button"
          @click="choose('audit')"
        >
          管理审计</button
        ><button
          :class="{ active: kind === 'tasks' }"
          role="tab"
          type="button"
          @click="choose('tasks')"
        >
          任务事件</button
        ><button
          :class="{ active: kind === 'provider' }"
          role="tab"
          type="button"
          @click="choose('provider')"
        >
          供应商调用
        </button>
      </div>
      <form class="card-header log-filters" @submit.prevent="load()">
        <input
          v-model="filter"
          class="input compact-input"
          :type="kind === 'tasks' ? 'number' : 'search'"
          :placeholder="
            kind === 'audit'
              ? '精确动作名称，如 ACCOUNT_CREATED'
              : kind === 'tasks'
                ? '项目数字 ID'
                : '精确模型名称'
          "
          :aria-label="
            kind === 'audit'
              ? '按动作筛选'
              : kind === 'tasks'
                ? '按项目 ID 筛选'
                : '按模型筛选'
          "
        /><button class="btn btn-secondary" type="submit" :disabled="loading">
          <Filter />应用筛选
        </button>
      </form>
      <StatePanel
        v-if="loading && !currentLength()"
        kind="loading"
        title="正在加载日志"
        description="正在读取只读日志记录。"
      /><StatePanel
        v-else-if="error && !currentLength()"
        kind="error"
        title="日志加载失败"
        :description="error"
        @retry="load()"
      /><StatePanel
        v-else-if="!currentLength()"
        kind="empty"
        title="当前筛选无日志"
        description="调整筛选条件后重新查询。"
      /><template v-else
        ><div
          v-if="error"
          class="form-error page-alert table-alert"
          role="alert"
        >
          {{ error }}
        </div>
        <div v-if="kind === 'audit'" class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作账号</th>
                <th>动作</th>
                <th>资源</th>
                <th>请求编号</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in audits"
                :key="`${row.requestId}-${row.createdAt}`"
              >
                <td data-label="时间">{{ date(row.createdAt) }}</td>
                <td data-label="操作账号">
                  {{ row.actorId ? `#${row.actorId}` : "系统" }}
                </td>
                <td data-label="动作">
                  <strong>{{ row.action }}</strong>
                </td>
                <td data-label="资源">
                  {{ row.resourceType }}
                  <div class="cell-note">{{ row.resourceId ?? "—" }}</div>
                </td>
                <td data-label="请求编号">
                  <code>{{ row.requestId }}</code>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="kind === 'tasks'" class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>项目 / 任务</th>
                <th>事件</th>
                <th>阶段</th>
                <th>进度</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in taskEvents"
                :key="`${row.taskId}-${row.createdAt}`"
              >
                <td data-label="时间">{{ date(row.createdAt) }}</td>
                <td data-label="项目 / 任务">
                  #{{ row.projectId }} / #{{ row.taskId }}
                </td>
                <td data-label="事件">
                  <strong>{{ row.type }}</strong>
                </td>
                <td data-label="阶段">{{ row.stage }}</td>
                <td data-label="进度">{{ row.progressPercent }}%</td>
                <td data-label="结果">
                  <StatusBadge
                    :label="row.errorCode ? '失败' : '正常'"
                    :tone="row.errorCode ? 'danger' : 'success'"
                  />
                  <div v-if="row.errorCode" class="cell-note error-text">
                    {{ row.errorCode }} · {{ row.errorMessage }}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>时间 / 调用</th>
                <th>项目 / 任务</th>
                <th>能力 / 模型</th>
                <th>语言</th>
                <th>耗时</th>
                <th>费用 / 状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in providerCalls" :key="row.publicId">
                <td data-label="时间 / 调用">
                  {{ date(row.createdAt) }}
                  <div class="cell-note">{{ row.publicId }}</div>
                </td>
                <td data-label="项目 / 任务">
                  #{{ row.projectId }} /
                  {{ row.taskId ? `#${row.taskId}` : "—" }}
                </td>
                <td data-label="能力 / 模型">
                  {{ capabilityLabels[row.capability] ?? row.capability }}
                  <div class="cell-note">{{ row.model }}</div>
                </td>
                <td data-label="语言">{{ row.language ?? "—" }}</td>
                <td data-label="耗时">
                  {{ row.durationMs == null ? "—" : `${row.durationMs} ms` }}
                </td>
                <td data-label="费用 / 状态">
                  <strong>{{ money(row.costMicrounit) }}</strong>
                  <div>
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

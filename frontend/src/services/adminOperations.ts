import { apiDownload, apiFetch } from "@/services/http";

export interface DashboardSummary {
  projectCount: number;
  successRate: number;
  queueBacklog: number;
  videoMinutes: number;
  todayCostMicrounit: number;
  monthCostMicrounit: number;
  providerStatus: { enabled: number };
}

export interface AdminTask {
  publicId: string;
  projectId: number;
  projectPublicId: string;
  projectName: string;
  createdBy: number;
  translationMode: "professional" | "youdao";
  language: string;
  status: number;
  stage: number;
  progressPercent: number;
  retryCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AdminImageGenerationJob {
  publicId: string;
  prompt: string;
  size: string;
  count: number;
  referenceCount: number;
  status: number;
  statusLabel: string;
  outputs: string[];
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  finishedAt: string | null;
  accountLoginName: string;
  accountDisplayName: string;
}

export interface AdminVideoGenerationJob {
  publicId: string;
  prompt: string;
  size: string;
  durationSeconds: number;
  tier: number;
  status: number;
  statusLabel: string;
  outputs: string[];
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  finishedAt: string | null;
  accountLoginName: string;
  accountDisplayName: string;
}

export interface ProviderConfig {
  publicId: string;
  providerCode: string;
  displayName: string;
  capability: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  status: 1 | 2;
  priority: number;
  supportedLocales: string[] | null;
  activeVersionId: string | null;
  modelName: string | null;
  endpointUrl: string | null;
  hasKey: boolean;
  createdAt: string;
  updatedAt: string;
}

export type ProviderCode =
  | "doubao_asr"
  | "ark"
  | "minimax"
  | "youdao_si"
  | "seedream"
  | "ark_vision"
  | "seedance_video";

export interface ProviderVersion {
  publicId: string;
  versionNo: number;
  modelName: string;
  endpointUrl: string;
  timeoutMs: number;
  hasKey: boolean;
  createdAt: string;
}

export interface ProviderPrice {
  publicId: string;
  versionId: string | null;
  capability: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  modelName: string;
  locale: string | null;
  billingUnit: "characters" | "tokens" | "milliseconds" | "seconds";
  unitSize: number;
  unitPriceMicrounit: number;
  currency: string;
  effectiveFrom: string;
  effectiveTo: string | null;
}

export interface ProviderCreateInput {
  providerCode: ProviderCode;
  displayName: string;
  capability: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  priority: number;
  supportedLocales: string[] | null;
  modelName: string;
  endpointUrl: string;
  timeoutMs: number;
  options?: Record<string, unknown>;
  apiKey: string;
}

export interface ProviderUpdateInput {
  displayName?: string;
  priority?: number;
  status?: 1 | 2;
  supportedLocales?: string[];
  modelName?: string;
  endpointUrl?: string;
  timeoutMs?: number;
  options?: Record<string, unknown>;
  apiKey?: string;
}

export interface ProviderPriceCreateInput {
  versionId: string;
  capability: 1 | 2 | 3 | 4 | 5 | 6 | 7;
  locale: string | null;
  billingUnit: ProviderPrice["billingUnit"];
  unitSize: number;
  unitPriceMicrounit: number;
  currency: "CNY";
  effectiveFrom: string;
  effectiveTo: string | null;
}

export interface CostSummaryItem {
  group: number | string | null;
  requestCount: number;
  costMicrounit: number;
  inputUnits: number;
  outputUnits: number;
}

export interface CostRecord {
  publicId: string;
  projectId: number;
  taskId: number | null;
  providerVersionId: number;
  capability: number;
  model: string;
  language: string | null;
  inputUnits: number;
  outputUnits: number;
  durationMs: number | null;
  status: number;
  unitPriceMicrounit: number;
  costMicrounit: number;
  errorCode: string | null;
  createdAt: string;
}

export interface AuditLogEntry {
  actorId: number | null;
  action: string;
  resourceType: string;
  resourceId: string | null;
  requestId: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  createdAt: string;
}

export interface TaskLogEntry {
  projectId: number;
  taskId: number;
  type: string;
  stage: number;
  progressPercent: number;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
}

export interface ProviderCallEntry {
  publicId: string;
  projectId: number;
  taskId: number | null;
  providerVersionId: number;
  capability: number;
  model: string;
  language: string | null;
  status: number;
  durationMs: number | null;
  costMicrounit: number;
  errorCode: string | null;
  createdAt: string;
}

export interface CursorPage<T> {
  items: T[];
  nextCursor: number | null;
}

function withQuery(
  path: string,
  params: Record<string, string | number | undefined>,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") query.set(key, String(value));
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export function getDashboard() {
  return apiFetch<DashboardSummary>("/api/v1/admin/dashboard");
}

export function listAdminTasks(
  params: {
    cursor?: number;
    limit?: number;
    status?: number;
    language?: string;
  } = {},
) {
  return apiFetch<CursorPage<AdminTask>>(
    withQuery("/api/v1/admin/tasks", {
      limit: params.limit ?? 50,
      cursor: params.cursor,
      status: params.status,
      language: params.language,
    }),
  );
}
export function cancelAdminTask(publicId: string) {
  return apiFetch<{ task: AdminTask }>(
    `/api/v1/admin/tasks/${encodeURIComponent(publicId)}/cancel`,
    { method: "POST" },
  );
}
export function retryAdminTask(publicId: string) {
  return apiFetch<{ task: AdminTask }>(
    `/api/v1/admin/tasks/${encodeURIComponent(publicId)}/retry`,
    { method: "POST" },
  );
}

export function listAdminImageGenerations(limit = 20, offset = 0) {
  return apiFetch<{ items: AdminImageGenerationJob[] }>(
    withQuery("/api/v1/admin/image-generations", { limit, offset }),
  );
}
export function downloadAdminImageGeneration(publicId: string, index: number) {
  return apiDownload(
    `/api/v1/admin/image-generations/${encodeURIComponent(publicId)}/images/${index}`,
  );
}

export function listAdminVideoGenerations(limit = 20, offset = 0) {
  return apiFetch<{ items: AdminVideoGenerationJob[] }>(
    withQuery("/api/v1/admin/video-generations", { limit, offset }),
  );
}
export function downloadAdminVideoGeneration(publicId: string) {
  return apiDownload(
    `/api/v1/admin/video-generations/${encodeURIComponent(publicId)}/video`,
  );
}
export function downloadAdminVideoGenerationReference(publicId: string) {
  return apiDownload(
    `/api/v1/admin/video-generations/${encodeURIComponent(publicId)}/reference`,
  );
}

export function listProviders() {
  return apiFetch<{ items: ProviderConfig[] }>("/api/v1/admin/providers");
}
export function createProvider(input: ProviderCreateInput) {
  return apiFetch<{ provider: ProviderConfig }>("/api/v1/admin/providers", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function updateProvider(
  provider: ProviderConfig,
  input: ProviderUpdateInput,
) {
  return apiFetch<{ provider: ProviderConfig; newVersionId: string | null }>(
    `/api/v1/admin/providers/${provider.publicId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ expectedUpdatedAt: provider.updatedAt, ...input }),
    },
  );
}
export function testProvider(publicId: string) {
  return apiFetch<{ result: string }>(
    `/api/v1/admin/providers/${publicId}/test`,
    { method: "POST" },
  );
}
export function listProviderVersions(publicId: string, cursor?: number) {
  return apiFetch<CursorPage<ProviderVersion>>(
    withQuery(`/api/v1/admin/providers/${publicId}/versions`, {
      limit: 20,
      cursor,
    }),
  );
}
export function activateProvider(provider: ProviderConfig, versionId: string) {
  return apiFetch<{ provider: ProviderConfig }>(
    `/api/v1/admin/providers/${provider.publicId}/activate`,
    {
      method: "POST",
      body: JSON.stringify({
        versionId,
        expectedUpdatedAt: provider.updatedAt,
      }),
    },
  );
}
export function listProviderPrices(versionId: string) {
  return apiFetch<{ items: ProviderPrice[] }>(
    withQuery("/api/v1/admin/providers/prices", { versionId }),
  );
}
export function createProviderPrice(input: ProviderPriceCreateInput) {
  return apiFetch<{ price: { publicId: string; unitPriceMicrounit: number } }>(
    "/api/v1/admin/providers/prices",
    { method: "POST", body: JSON.stringify(input) },
  );
}

export interface CostFilters {
  start?: string;
  end?: string;
  language?: string;
  capability?: number;
  model?: string;
}
export function getCostSummary(filters: CostFilters, groupBy = "capability") {
  return apiFetch<{ groupBy: string; items: CostSummaryItem[] }>(
    withQuery("/api/v1/admin/costs/summary", { groupBy, ...filters }),
  );
}
export function listCostRecords(filters: CostFilters, cursor?: number) {
  return apiFetch<CursorPage<CostRecord>>(
    withQuery("/api/v1/admin/costs/records", { limit: 50, cursor, ...filters }),
  );
}
export function exportCostRecords(filters: CostFilters) {
  return apiDownload(
    withQuery("/api/v1/admin/costs/records", {
      limit: 200,
      format: "csv",
      ...filters,
    }),
  );
}

export function listAuditLogs(params: { cursor?: number; action?: string }) {
  return apiFetch<CursorPage<AuditLogEntry>>(
    withQuery("/api/v1/admin/logs/audit", { limit: 50, ...params }),
  );
}
export function listTaskLogs(params: { cursor?: number; projectId?: number }) {
  return apiFetch<CursorPage<TaskLogEntry>>(
    withQuery("/api/v1/admin/logs/tasks", { limit: 50, ...params }),
  );
}
export function listProviderCalls(params: { cursor?: number; model?: string }) {
  return apiFetch<CursorPage<ProviderCallEntry>>(
    withQuery("/api/v1/admin/logs/provider-calls", { limit: 50, ...params }),
  );
}

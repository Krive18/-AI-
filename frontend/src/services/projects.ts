import { apiDownload, apiFetch } from "@/services/http";

export interface TranslationProject {
  publicId: string;
  name: string;
  translationMode: TranslationMode;
  status: number;
  progressPercent: number;
  sourceFilename: string;
  sourceSizeBytes: number;
  estimatedCostMicrounit: number;
  actualCostMicrounit: number;
  createdAt: string;
}

export type TranslationMode = "professional" | "youdao" | "subtitle";

export interface TranslationSubtask {
  publicId: string;
  language: string;
  status: number;
  stage: number;
  progressPercent: number;
  retryCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  voiceId: string | null;
}

export interface ProjectDetail {
  project: TranslationProject;
  tasks: TranslationSubtask[];
}
export interface ProjectPage {
  items: TranslationProject[];
  nextCursor: number | null;
}

export interface TranslationOptions {
  modes: {
    professional: { available: boolean; supportedLocales: string[] };
    youdao: { available: boolean; supportedLocales: string[] };
    subtitle: { available: boolean; supportedLocales: string[] };
  };
}

const CHUNK_BYTES = 4 * 1024 * 1024;

export function listProjects(
  cursor?: number,
  filters: { keyword?: string; state?: string } = {},
) {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", String(cursor));
  if (filters.keyword) query.set("keyword", filters.keyword);
  if (filters.state) query.set("state", filters.state);
  return apiFetch<ProjectPage>(`/api/v1/projects?${query}`);
}

export function getTranslationOptions() {
  return apiFetch<TranslationOptions>("/api/v1/projects/translation-options");
}

export function getProject(publicId: string) {
  return apiFetch<ProjectDetail>(
    `/api/v1/projects/${encodeURIComponent(publicId)}`,
  );
}
export function cancelProject(publicId: string) {
  return apiFetch<{ project: TranslationProject }>(
    `/api/v1/projects/${encodeURIComponent(publicId)}/cancel`,
    { method: "POST" },
  );
}
export function retryProject(publicId: string) {
  return apiFetch<{ project: TranslationProject }>(
    `/api/v1/projects/${encodeURIComponent(publicId)}/retry`,
    { method: "POST" },
  );
}
export function retryProjectTask(projectId: string, taskId: string) {
  return apiFetch<{ task: TranslationSubtask }>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/retry`,
    { method: "POST" },
  );
}
export function downloadProjectAsset(
  projectId: string,
  taskId: string,
  kind: "video" | "subtitle",
) {
  return apiDownload(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/download/${kind}`,
  );
}
export function previewProjectVideoUrl(projectId: string, taskId: string) {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/preview`;
}

export interface TaskSubtitles {
  source_text: string;
  target_text: string;
  segment_count: number;
}

export function fetchTaskSubtitles(projectId: string, taskId: string) {
  return apiFetch<TaskSubtitles>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/subtitles`,
  );
}

export function taskSubtitlePreviewUrl(projectId: string, taskId: string) {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/preview-subtitles`;
}

export async function uploadAndCreateProject(input: {
  file: File;
  name: string;
  targetLocales: string[];
  translationMode: TranslationMode;
  voiceId?: string;
  idempotencyKey: string;
  onProgress: (percent: number) => void;
}) {
  const started = await apiFetch<{ uploadToken: string }>(
    "/api/v1/projects/uploads",
    {
      method: "POST",
      body: JSON.stringify({
        filename: input.file.name,
        contentType: input.file.type || "application/octet-stream",
        totalBytes: input.file.size,
      }),
    },
  );
  let offset = 0;
  while (offset < input.file.size) {
    const chunk = input.file.slice(
      offset,
      Math.min(offset + CHUNK_BYTES, input.file.size),
    );
    const form = new FormData();
    form.append("file", chunk, input.file.name);
    const result = await apiFetch<{ receivedBytes: number }>(
      `/api/v1/projects/uploads/${encodeURIComponent(started.uploadToken)}/chunks?offset=${offset}`,
      { method: "PUT", body: form },
    );
    if (
      result.receivedBytes <= offset ||
      result.receivedBytes > input.file.size
    )
      throw new Error("上传服务返回了无效的分片位置");
    offset = result.receivedBytes;
    input.onProgress(Math.round((offset / input.file.size) * 95));
  }
  await apiFetch(
    `/api/v1/projects/uploads/${encodeURIComponent(started.uploadToken)}/complete`,
    { method: "POST" },
  );
  input.onProgress(97);
  const result = await apiFetch<{ project: TranslationProject }>(
    "/api/v1/projects",
    {
      method: "POST",
      headers: { "Idempotency-Key": input.idempotencyKey },
      body: JSON.stringify({
        name: input.name,
        uploadToken: started.uploadToken,
        targetLocales: input.targetLocales,
        translationMode: input.translationMode,
        voiceId: input.voiceId ?? null,
      }),
    },
  );
  input.onProgress(100);
  return result.project;
}

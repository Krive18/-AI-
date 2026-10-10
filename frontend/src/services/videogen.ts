import { apiDownload, apiFetch } from "@/services/http";

export type VideoResolution = "480p" | "720p";
export type VideoTier = 1 | 2 | 3;

export interface VideoGenerationJob {
  publicId: string;
  prompt: string;
  size: VideoResolution;
  durationSeconds: number;
  tier: VideoTier;
  tierLabel: string;
  hasReference: boolean;
  status: number;
  statusLabel: string;
  outputs: string[];
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface VideoGenerateInput {
  prompt: string;
  tier: VideoTier;
  resolution: VideoResolution;
  durationSeconds: number;
  reference: string;
}

export function createVideoGeneration(input: VideoGenerateInput) {
  return apiFetch<{ job: VideoGenerationJob }>("/api/v1/videos", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listVideoGenerations(limit = 20, offset = 0) {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetch<{ items: VideoGenerationJob[] }>(`/api/v1/videos?${query}`);
}

export function getVideoGeneration(publicId: string) {
  return apiFetch<{ job: VideoGenerationJob }>(
    `/api/v1/videos/${encodeURIComponent(publicId)}`,
  );
}

export function downloadVideo(publicId: string) {
  return apiDownload(`/api/v1/videos/${encodeURIComponent(publicId)}/video`);
}

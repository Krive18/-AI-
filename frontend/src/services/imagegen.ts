import { apiDownload, apiFetch } from "@/services/http";

export type ImageSize = "2K" | "3K" | "4K";

export interface ImageGenerationJob {
  publicId: string;
  prompt: string;
  size: ImageSize;
  count: number;
  referenceCount: number;
  status: number;
  statusLabel: string;
  outputs: string[];
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface ImageGenerateInput {
  prompt: string;
  size: ImageSize;
  count: number;
  references: string[];
}

export function createImageGeneration(input: ImageGenerateInput) {
  return apiFetch<{ job: ImageGenerationJob }>("/api/v1/image-generations", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listImageGenerations(limit = 20, offset = 0) {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetch<{ items: ImageGenerationJob[] }>(
    `/api/v1/image-generations?${query}`,
  );
}

export function getImageGeneration(publicId: string) {
  return apiFetch<{ job: ImageGenerationJob }>(
    `/api/v1/image-generations/${encodeURIComponent(publicId)}`,
  );
}

export function downloadImage(publicId: string, index: number) {
  return apiDownload(
    `/api/v1/image-generations/${encodeURIComponent(publicId)}/images/${index}`,
  );
}

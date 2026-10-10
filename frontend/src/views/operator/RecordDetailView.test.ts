// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RecordDetailView from "./RecordDetailView.vue";

const testState = vi.hoisted(() => ({
  getProject: vi.fn(),
  fetchTaskSubtitles: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { projectId: "project-1" } }),
}));

vi.mock("@/services/projects", () => ({
  getProject: testState.getProject,
  cancelProject: vi.fn(),
  retryProject: vi.fn(),
  retryProjectTask: vi.fn(),
  downloadProjectAsset: vi.fn(),
  previewProjectVideoUrl: vi.fn(() => "/preview.mp4"),
  fetchTaskSubtitles: testState.fetchTaskSubtitles,
  taskSubtitlePreviewUrl: vi.fn(
    () => "/api/v1/projects/project-1/tasks/task-1/preview-subtitles",
  ),
}));

describe("RecordDetailView", () => {
  beforeEach(() => {
    testState.getProject.mockReset().mockResolvedValue({
      project: {
        publicId: "project-1",
        name: "海外发布视频",
        translationMode: "youdao",
        status: 7,
        progressPercent: 100,
        sourceFilename: "source.mp4",
        sourceSizeBytes: 1024,
        estimatedCostMicrounit: 7_200_000,
        actualCostMicrounit: 6_800_000,
        createdAt: "2026-09-02T10:00:00Z",
      },
      tasks: [],
    });
    testState.fetchTaskSubtitles.mockReset().mockResolvedValue({
      source_text: "",
      target_text: "",
      segment_count: 0,
    });
  });

  it("项目详情不向运营成员展示费用数据", async () => {
    const wrapper = mount(RecordDetailView, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).not.toContain("费用");
    expect(wrapper.text()).not.toContain("预估");
    expect(wrapper.text()).not.toContain("¥");
    expect(wrapper.text()).toContain("海外发布视频");
    expect(wrapper.text()).toContain("智能翻译");

    wrapper.unmount();
  });

  it("为预览任务展示字幕文本卡片并提供复制与下载入口", async () => {
    testState.getProject.mockResolvedValue({
      project: {
        publicId: "project-1",
        name: "海外发布视频",
        translationMode: "professional",
        status: 7,
        progressPercent: 100,
        sourceFilename: "source.mp4",
        sourceSizeBytes: 1024,
        estimatedCostMicrounit: 7_200_000,
        actualCostMicrounit: 6_800_000,
        createdAt: "2026-09-02T10:00:00Z",
      },
      tasks: [
        {
          publicId: "task-1",
          language: "en-US",
          status: 5,
          stage: 5,
          progressPercent: 100,
          retryCount: 0,
          errorCode: null,
          errorMessage: null,
        },
      ],
    });
    testState.fetchTaskSubtitles.mockResolvedValue({
      source_text: "你好，世界",
      target_text: "Hello world",
      segment_count: 1,
    });
    const wrapper = mount(RecordDetailView, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();

    expect(testState.fetchTaskSubtitles).toHaveBeenCalledWith(
      "project-1",
      "task-1",
    );
    expect(wrapper.text()).toContain("字幕文本");
    expect(wrapper.text()).toContain("翻译前字幕");
    expect(wrapper.text()).toContain("翻译后字幕");
    expect(wrapper.text()).toContain("下载 SRT");
    const track = wrapper.find("video track");
    expect(track.exists()).toBe(true);

    wrapper.unmount();
  });
});

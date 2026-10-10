// @vitest-environment jsdom

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/http";
import type { TranslationProject } from "@/services/projects";
import { useToastsStore } from "@/stores/toasts";

import RecordsView from "./RecordsView.vue";

const testState = vi.hoisted(() => ({
  listProjects: vi.fn(),
  retryProject: vi.fn(),
}));

vi.mock("@/services/projects", () => ({
  listProjects: testState.listProjects,
  retryProject: testState.retryProject,
}));

function project(
  overrides: Partial<TranslationProject> = {},
): TranslationProject {
  return {
    publicId: "project-1",
    name: "海外发布视频",
    translationMode: "professional",
    status: 6,
    progressPercent: 45,
    sourceFilename: "source.mp4",
    sourceSizeBytes: 1024,
    estimatedCostMicrounit: 7_200_000,
    actualCostMicrounit: 6_800_000,
    createdAt: "2026-09-02T10:00:00Z",
    ...overrides,
  };
}

function page(items: TranslationProject[], nextCursor: number | null = null) {
  return { items, nextCursor };
}

function mountView() {
  return mount(RecordsView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: { template: "<a><slot /></a>" },
      },
    },
  });
}

describe("RecordsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    testState.listProjects.mockReset().mockResolvedValue(page([project()]));
    testState.retryProject
      .mockReset()
      .mockResolvedValue({ project: project() });
  });

  it("首次加载用骨架占位，列表只展示运营需要的任务信息", async () => {
    const wrapper = mountView();
    expect(wrapper.findAll(".skeleton")).toHaveLength(4);
    await flushPromises();

    expect(wrapper.text()).not.toContain("费用");
    expect(wrapper.text()).not.toContain("¥");
    expect(wrapper.text()).toContain("海外发布视频");
    expect(wrapper.text()).toContain("专业精译");
  });

  it("空列表渲染空状态与新建翻译入口", async () => {
    testState.listProjects.mockResolvedValue(page([]));
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("没有符合条件的翻译记录");
    const links = wrapper.findAll("a");
    expect(links.some((link) => link.text().includes("新建翻译"))).toBe(true);
  });

  it("状态 chips 切换后带 state 参数重新加载", async () => {
    const wrapper = mountView();
    await flushPromises();

    await wrapper.findAll("button.chip")[2].trigger("click");
    await flushPromises();

    expect(testState.listProjects).toHaveBeenLastCalledWith(undefined, {
      keyword: undefined,
      state: "succeeded",
    });
  });

  it("失败行显示重试按钮，二次确认后才提交，成功提示并刷新", async () => {
    testState.listProjects.mockResolvedValue(page([project({ status: 9 })]));
    const wrapper = mountView();
    await flushPromises();

    const retryButton = wrapper
      .findAll("button")
      .find((button) => button.text() === "重试");
    expect(retryButton).toBeDefined();
    expect(wrapper.find("tr.row-failed").exists()).toBe(true);

    await retryButton!.trigger("click");
    expect(testState.retryProject).not.toHaveBeenCalled();
    expect(retryButton!.text()).toContain("确认重试？");

    await retryButton!.trigger("click");
    expect(testState.retryProject).toHaveBeenCalledWith("project-1");
    await flushPromises();

    const toasts = useToastsStore();
    expect(toasts.items.map((item) => item.message)).toContain("已重新提交");
    expect(testState.listProjects.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("重试失败时提示后端错误信息", async () => {
    testState.listProjects.mockResolvedValue(page([project({ status: 9 })]));
    testState.retryProject.mockRejectedValue(
      new ApiError(
        "PROJECT_NOT_RETRYABLE",
        "仅失败或部分成功项目可以重试",
        "req-1",
        409,
      ),
    );
    const wrapper = mountView();
    await flushPromises();

    const retryButton = wrapper
      .findAll("button")
      .find((button) => button.text() === "重试")!;
    await retryButton.trigger("click");
    await retryButton.trigger("click");
    await flushPromises();

    const toasts = useToastsStore();
    expect(toasts.items).toHaveLength(1);
    expect(toasts.items[0].kind).toBe("error");
    expect(toasts.items[0].message).toBe("仅失败或部分成功项目可以重试");
  });

  it("创建时间提供绝对时间悬停提示", async () => {
    const wrapper = mountView();
    await flushPromises();

    const cell = wrapper.find('td[data-label="创建时间"]');
    // 后端时间为 UTC（2026-09-02T10:00:00Z），悬停提示按本地时区（东八区）展示
    expect(cell.attributes("title")).toBe("2026-09-02 18:00");
  });
});

describe("RecordsView 轮询与搜索", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    testState.listProjects.mockReset();
    testState.retryProject
      .mockReset()
      .mockResolvedValue({ project: project() });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("存在进行中项目时 4 秒轮询，全部终态后自动停止", async () => {
    testState.listProjects
      .mockResolvedValueOnce(page([project({ status: 6 })]))
      .mockResolvedValue(page([project({ status: 7 })]));
    mountView();
    await flushPromises();
    expect(testState.listProjects).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(4000);
    expect(testState.listProjects).toHaveBeenCalledTimes(2);

    // 第二次返回已完成（终态），轮询应停止。
    await vi.advanceTimersByTimeAsync(12000);
    expect(testState.listProjects).toHaveBeenCalledTimes(2);
  });

  it("离开页面后清除轮询定时器", async () => {
    testState.listProjects.mockResolvedValue(page([project({ status: 6 })]));
    const wrapper = mountView();
    await flushPromises();

    await vi.advanceTimersByTimeAsync(4000);
    expect(testState.listProjects).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(12000);
    expect(testState.listProjects).toHaveBeenCalledTimes(2);
  });

  it("搜索输入防抖 300ms 后以 keyword 参数重新加载", async () => {
    testState.listProjects.mockResolvedValue(page([project()]));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find("input[type='search']").setValue("发布会");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(testState.listProjects).toHaveBeenLastCalledWith(undefined, {
      keyword: "发布会",
      state: undefined,
    });
  });
});

// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useToastsStore } from "@/stores/toasts";
import NewTranslationView from "./NewTranslationView.vue";

const pushMock = vi.fn();

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/services/projects", () => ({
  getTranslationOptions: vi.fn().mockResolvedValue({
    modes: {
      professional: {
        available: true,
        supportedLocales: [
          "en-US",
          "ja-JP",
          "ko-KR",
          "vi-VN",
          "ms-MY",
          "th-TH",
          "fil-PH",
          "de-DE",
          "fr-FR",
        ],
      },
      youdao: {
        available: true,
        supportedLocales: [
          "en-US",
          "ja-JP",
          "ko-KR",
          "vi-VN",
          "ms-MY",
          "th-TH",
        ],
      },
      subtitle: {
        available: true,
        supportedLocales: [
          "en-US",
          "ja-JP",
          "ko-KR",
          "vi-VN",
          "ms-MY",
          "th-TH",
          "fil-PH",
          "de-DE",
          "fr-FR",
        ],
      },
    },
  }),
  uploadAndCreateProject: vi.fn(),
}));

import {
  getTranslationOptions,
  uploadAndCreateProject,
} from "@/services/projects";

const OPTIONS = {
  modes: {
    professional: {
      available: true,
      supportedLocales: [
        "en-US",
        "ja-JP",
        "ko-KR",
        "vi-VN",
        "ms-MY",
        "th-TH",
        "fil-PH",
        "de-DE",
        "fr-FR",
      ],
    },
    youdao: {
      available: true,
      supportedLocales: ["en-US", "ja-JP", "ko-KR", "vi-VN", "ms-MY", "th-TH"],
    },
    subtitle: {
      available: true,
      supportedLocales: [
        "en-US",
        "ja-JP",
        "ko-KR",
        "vi-VN",
        "ms-MY",
        "th-TH",
        "fil-PH",
        "de-DE",
        "fr-FR",
      ],
    },
  },
};

function videoFile(name = "宣传片.mp4", size = 4 * 1024 * 1024) {
  const file = new File([new Uint8Array(8)], name, { type: "video/mp4" });
  Object.defineProperty(file, "size", { value: size, configurable: true });
  return file;
}

function dropFile(wrapper: ReturnType<typeof mount>, file: File) {
  return wrapper.find(".upload-zone").trigger("drop", {
    dataTransfer: { files: [file], types: ["Files"] },
  });
}

describe("NewTranslationView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    pushMock.mockClear();
    vi.mocked(getTranslationOptions).mockResolvedValue(OPTIONS);
    vi.mocked(uploadAndCreateProject).mockReset();
  });

  it("不向运营成员展示费用预估", () => {
    const wrapper = mount(NewTranslationView);

    expect(wrapper.text()).not.toContain("预估");
    expect(wrapper.text()).not.toContain("费用");
    expect(wrapper.text()).not.toContain("¥");
  });

  it("默认选择专业精译并提供智能翻译入口", () => {
    const wrapper = mount(NewTranslationView);

    const professional = wrapper.get<HTMLInputElement>(
      'input[name="translation-mode"][value="professional"]',
    );
    expect(professional.element.checked).toBe(true);
    expect(wrapper.text()).toContain("专业精译");
    expect(wrapper.text()).toContain("智能翻译");
  });

  it("选择菲律宾语后不能使用智能翻译", async () => {
    const wrapper = mount(NewTranslationView);
    const filipino = wrapper.get<HTMLInputElement>('input[value="fil-PH"]');

    await filipino.setValue(true);

    const youdao = wrapper.get<HTMLInputElement>(
      'input[name="translation-mode"][value="youdao"]',
    );
    expect(youdao.element.disabled).toBe(true);
    expect(wrapper.text()).toContain("智能翻译暂不支持所选语言");
  });

  it("智能翻译供应商未配置时禁用对应路径", async () => {
    vi.mocked(getTranslationOptions).mockResolvedValueOnce({
      modes: {
        professional: {
          available: true,
          supportedLocales: [
            "en-US",
            "ja-JP",
            "ko-KR",
            "vi-VN",
            "ms-MY",
            "th-TH",
            "fil-PH",
            "de-DE",
            "fr-FR",
          ],
        },
        youdao: { available: false, supportedLocales: [] },
        subtitle: {
          available: true,
          supportedLocales: [
            "en-US",
            "ja-JP",
            "ko-KR",
            "vi-VN",
            "ms-MY",
            "th-TH",
            "fil-PH",
            "de-DE",
            "fr-FR",
          ],
        },
      },
    });
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    const youdao = wrapper.get<HTMLInputElement>(
      'input[name="translation-mode"][value="youdao"]',
    );
    expect(youdao.element.disabled).toBe(true);
    expect(wrapper.text()).toContain("管理员尚未配置");
  });

  it("字幕翻译入口在当前版本隐藏", async () => {
    vi.mocked(getTranslationOptions).mockResolvedValueOnce({
      modes: {
        professional: {
          available: true,
          supportedLocales: [
            "en-US",
            "ja-JP",
            "ko-KR",
            "vi-VN",
            "ms-MY",
            "th-TH",
            "fil-PH",
            "de-DE",
            "fr-FR",
          ],
        },
        youdao: {
          available: true,
          supportedLocales: [
            "en-US",
            "ja-JP",
            "ko-KR",
            "vi-VN",
            "ms-MY",
            "th-TH",
          ],
        },
        subtitle: { available: true, supportedLocales: ["en-US"] },
      },
    });
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    expect(
      wrapper.find('input[name="translation-mode"][value="subtitle"]').exists(),
    ).toBe(false);
    expect(wrapper.text()).not.toContain("字幕翻译");
  });
});

describe("NewTranslationView 上传校验", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    pushMock.mockClear();
    vi.mocked(getTranslationOptions).mockResolvedValue(OPTIONS);
    vi.mocked(uploadAndCreateProject).mockReset();
  });

  it("拖入不支持格式的文件时在上传区块就地提示并阻止选择", async () => {
    const wrapper = mount(NewTranslationView);

    await dropFile(wrapper, videoFile("说明.txt"));

    expect(wrapper.get('[data-section="upload"]').text()).toContain(
      "仅支持 MP4、MOV 或 MKV 文件",
    );
    expect(wrapper.text()).not.toContain("校验通过");
    expect(wrapper.get(".summary-list").text()).toContain("尚未选择");
  });

  it("拖入超过 2 GB 的文件时提示大小限制", async () => {
    const wrapper = mount(NewTranslationView);

    await dropFile(wrapper, videoFile("大文件.mp4", 3 * 1024 * 1024 * 1024));

    expect(wrapper.get('[data-section="upload"]').text()).toContain(
      "视频大小必须在 2 GB 以内",
    );
  });

  it("拖入合法文件后显示文件名、大小与校验通过状态", async () => {
    const wrapper = mount(NewTranslationView);

    await dropFile(wrapper, videoFile("宣传片.mp4", 4 * 1024 * 1024));

    const status = wrapper.get(".file-status");
    expect(status.text()).toContain("宣传片.mp4");
    expect(status.text()).toContain("4.0 MB");
    expect(status.text()).toContain("校验通过");
    expect(wrapper.get<HTMLInputElement>("#project-name").element.value).toBe(
      "宣传片",
    );
  });
});

describe("NewTranslationView 字段级校验", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    pushMock.mockClear();
    vi.mocked(getTranslationOptions).mockResolvedValue(OPTIONS);
    vi.mocked(uploadAndCreateProject).mockReset();
  });

  it("未选文件提交时不调用创建接口，错误落在上传卡并提示 toast", async () => {
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    await wrapper.get(".estimate-card button").trigger("click");

    expect(uploadAndCreateProject).not.toHaveBeenCalled();
    expect(wrapper.get('[data-section="upload"]').classes()).toContain(
      "card-error",
    );
    expect(wrapper.get('[data-section="upload"]').text()).toContain(
      "请选择需要翻译的视频文件",
    );
    const toasts = useToastsStore();
    expect(toasts.items).toHaveLength(1);
    expect(toasts.items[0].kind).toBe("error");
  });

  it("未选目标语言时错误落在语言卡", async () => {
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    await dropFile(wrapper, videoFile());
    await wrapper
      .get(".language-tools .link-button:last-child")
      .trigger("click");
    await wrapper.get(".estimate-card button").trigger("click");

    expect(uploadAndCreateProject).not.toHaveBeenCalled();
    expect(wrapper.get('[data-section="languages"]').text()).toContain(
      "请至少选择一种目标语言",
    );
    expect(wrapper.get('[data-section="languages"]').classes()).toContain(
      "card-error",
    );
  });

  it("全选选中当前翻译方式支持的全部语言，清空后交付文案提示先选语言", async () => {
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    await wrapper
      .get(".language-tools .link-button:first-child")
      .trigger("click");

    const checked = wrapper.findAll<HTMLInputElement>(
      '.language-option input[type="checkbox"]',
    );
    expect(checked.filter((box) => box.element.checked)).toHaveLength(9);
    expect(wrapper.get('[data-testid="delivery-summary"]').text()).toBe(
      "将生成 9 条配音成片、9 个 SRT 字幕文件；成片不含烧录字幕。",
    );

    await wrapper
      .get(".language-tools .link-button:last-child")
      .trigger("click");

    expect(wrapper.get('[data-testid="delivery-summary"]').text()).toBe(
      "请先选择目标语言。",
    );
  });

  it("交付文案随已选语言数实时更新", async () => {
    const wrapper = mount(NewTranslationView);

    expect(wrapper.get('[data-testid="delivery-summary"]').text()).toContain(
      "1 条配音成片",
    );

    await wrapper.get<HTMLInputElement>('input[value="ja-JP"]').setValue(true);

    expect(wrapper.get('[data-testid="delivery-summary"]').text()).toBe(
      "将生成 2 条配音成片、2 个 SRT 字幕文件；成片不含烧录字幕。",
    );
  });
});

describe("NewTranslationView 提交", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    pushMock.mockClear();
    vi.stubGlobal("crypto", { randomUUID: () => "idempotency-key-1" });
    vi.mocked(getTranslationOptions).mockResolvedValue(OPTIONS);
    vi.mocked(uploadAndCreateProject).mockReset();
  });

  it("提交成功后提示已创建并跳转详情页", async () => {
    vi.mocked(uploadAndCreateProject).mockResolvedValue({
      publicId: "project-1",
    } as unknown as Awaited<ReturnType<typeof uploadAndCreateProject>>);
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    await dropFile(wrapper, videoFile());
    await wrapper.get(".estimate-card button").trigger("click");
    await flushPromises();

    expect(uploadAndCreateProject).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith({
      name: "translation-detail",
      params: { projectId: "project-1" },
    });
    const toasts = useToastsStore();
    expect(toasts.items).toHaveLength(1);
    expect(toasts.items[0].message).toBe("已创建翻译任务");
    expect(toasts.items[0].kind).toBe("success");
  });

  it("提交失败时保留全局错误提示并提示错误 toast", async () => {
    vi.mocked(uploadAndCreateProject).mockRejectedValue(new Error("网络中断"));
    const wrapper = mount(NewTranslationView);
    await flushPromises();

    await dropFile(wrapper, videoFile());
    await wrapper.get(".estimate-card button").trigger("click");
    await flushPromises();

    expect(wrapper.find(".page-alert").text()).toContain("网络中断");
    const toasts = useToastsStore();
    expect(toasts.items).toHaveLength(1);
    expect(toasts.items[0].kind).toBe("error");
    expect(toasts.items[0].message).toBe("网络中断");
    expect(pushMock).not.toHaveBeenCalled();
  });
});

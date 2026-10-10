// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ProviderEditor from "@/components/provider/ProviderEditor.vue";
import type { ProviderCreateInput } from "@/services/adminOperations";

describe("ProviderEditor", () => {
  it("offers only production provider presets", () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    expect(
      wrapper
        .findAll("#provider-code option")
        .map((option) => option.attributes("value")),
    ).toEqual([
      "doubao_asr",
      "ark",
      "minimax",
      "youdao_si",
      "seedream",
      "ark_vision",
      "seedance_video",
    ]);
  });

  it("prefills the official Seedream image generation fields", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-code").setValue("seedream");

    expect(wrapper.get<HTMLInputElement>("#provider-model").element.value).toBe(
      "doubao-seedream-5-0-260128",
    );
    expect(
      wrapper.get<HTMLInputElement>("#provider-endpoint").element.value,
    ).toBe("https://ark.cn-beijing.volces.com/api/v3/images/generations");
    expect(
      wrapper.get<HTMLInputElement>("#provider-timeout").element.value,
    ).toBe("120000");
    expect(wrapper.get("label[for='provider-key']").text()).toBe("API Key");
  });

  it("prefills the official Ark vision subtitle OCR fields", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-code").setValue("ark_vision");

    expect(wrapper.get<HTMLInputElement>("#provider-model").element.value).toBe(
      "doubao-seed-2-0-lite-260428",
    );
    expect(
      wrapper.get<HTMLInputElement>("#provider-endpoint").element.value,
    ).toBe("https://ark.cn-beijing.volces.com/api/v3/chat/completions");
    expect(
      wrapper.get<HTMLInputElement>("#provider-timeout").element.value,
    ).toBe("60000");
    expect(wrapper.get("label[for='provider-key']").text()).toBe("API Key");
  });

  it("prefills the official Youdao simultaneous interpretation fields", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-code").setValue("youdao_si");

    expect(wrapper.get<HTMLInputElement>("#provider-model").element.value).toBe(
      "youdao-simultaneous-interpretation",
    );
    expect(
      wrapper.get<HTMLInputElement>("#provider-endpoint").element.value,
    ).toBe("wss://openapi.youdao.com/stream-audio/stream-si");
    expect(wrapper.get<HTMLInputElement>("#option-app-key").element.value).toBe(
      "",
    );
    expect(wrapper.get("label[for='provider-key']").text()).toBe("API Key");
  });

  it("prefills the official Doubao ASR connection fields", () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    expect(wrapper.get<HTMLInputElement>("#provider-model").element.value).toBe(
      "bigmodel",
    );
    expect(
      wrapper.get<HTMLInputElement>("#provider-endpoint").element.value,
    ).toBe("https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit");
    expect(
      wrapper.get<HTMLInputElement>("#option-query-url").element.value,
    ).toBe("https://openspeech.bytedance.com/api/v3/auc/bigmodel/query");
    expect(
      wrapper.get<HTMLInputElement>("#option-resource-id").element.value,
    ).toBe("volc.seedasr.auc");
    expect(wrapper.find("#option-app-id").exists()).toBe(false);
    expect(wrapper.get("label[for='provider-key']").text()).toBe("API Key");
  });

  it("prefills the official video generation fields", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-code").setValue("seedance_video");

    expect(
      wrapper.get<HTMLInputElement>("#provider-endpoint").element.value,
    ).toBe(
      "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
    );
    expect(
      wrapper.get<HTMLInputElement>("#provider-timeout").element.value,
    ).toBe("30000");
    expect(
      wrapper.get<HTMLInputElement>("#option-video-model-standard").element
        .value,
    ).toBe("doubao-seedance-2-0-260128");
    expect(
      wrapper.get<HTMLInputElement>("#option-video-model-fast").element.value,
    ).toBe("doubao-seedance-2-0-fast-260128");
    expect(
      wrapper.get<HTMLInputElement>("#option-video-model-mini").element.value,
    ).toBe("doubao-seedance-2-0-mini-260615");
    expect(wrapper.get("label[for='provider-key']").text()).toBe("API Key");
  });

  it("submits tiered video models as nested options", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-code").setValue("seedance_video");
    await wrapper.get("#provider-key").setValue("secret-api-key");
    await wrapper.get("form").trigger("submit");

    const payload = wrapper.emitted("save")?.[0]?.[0] as ProviderCreateInput;
    expect(payload.capability).toBe(7);
    expect(payload.options).toEqual({
      models: {
        standard: "doubao-seedance-2-0-260128",
        fast: "doubao-seedance-2-0-fast-260128",
        mini: "doubao-seedance-2-0-mini-260615",
      },
    });
  });

  it("submits only non-secret Doubao options alongside the API key", async () => {
    const wrapper = mount(ProviderEditor, { props: { mode: "create" } });

    await wrapper.get("#provider-key").setValue("secret-api-key");
    await wrapper.get("form").trigger("submit");

    const payload = wrapper.emitted("save")?.[0]?.[0] as ProviderCreateInput;
    expect(payload).toMatchObject({
      apiKey: "secret-api-key",
      options: {
        query_url: "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
        resource_id: "volc.seedasr.auc",
      },
    });
    expect(payload.options).not.toHaveProperty("app_id");
  });
});

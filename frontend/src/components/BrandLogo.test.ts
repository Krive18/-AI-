// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import BrandLogo from "./BrandLogo.vue";

describe("BrandLogo", () => {
  it("显示寰语品牌和可选副标题", () => {
    const wrapper = mount(BrandLogo, {
      props: { subtitle: "智能视频全球化工作台" },
    });

    expect(wrapper.text()).toContain("寰语");
    expect(wrapper.text()).toContain("智能视频全球化工作台");
    expect(wrapper.get("svg").attributes("aria-hidden")).toBe("true");
  });

  it("紧凑模式仍保留可读品牌名", () => {
    const wrapper = mount(BrandLogo, { props: { compact: true } });

    expect(wrapper.classes()).toContain("brand-logo--compact");
    expect(wrapper.get(".brand-logo__name").text()).toBe("寰语");
  });
});

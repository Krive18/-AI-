// @vitest-environment jsdom

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { applyInitialTheme, useThemeStore } from "./theme";

describe("useThemeStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("默认暗色，不写 data-theme 时初始化也不产生闪烁", () => {
    const store = useThemeStore();

    expect(store.mode).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("读取 localStorage 中的有效值初始化", () => {
    localStorage.setItem("ai-translation-theme", "light");

    const store = useThemeStore();

    expect(store.mode).toBe("light");
  });

  it("localStorage 中的无效值回退为暗色", () => {
    localStorage.setItem("ai-translation-theme", "solarized");

    const store = useThemeStore();

    expect(store.mode).toBe("dark");
  });

  it("toggle 在明暗之间切换并同步 data-theme 与持久化", () => {
    const store = useThemeStore();

    store.toggle();
    expect(store.mode).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("ai-translation-theme")).toBe("light");

    store.toggle();
    expect(store.mode).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("ai-translation-theme")).toBe("dark");
  });

  it("set 直接指定主题并持久化", () => {
    const store = useThemeStore();

    store.set("light");

    expect(store.mode).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("ai-translation-theme")).toBe("light");
  });

  it("applyInitialTheme 在挂载前应用持久化的主题", () => {
    localStorage.setItem("ai-translation-theme", "light");

    const mode = applyInitialTheme();

    expect(mode).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("applyInitialTheme 无存储时回退暗色", () => {
    const mode = applyInitialTheme();

    expect(mode).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

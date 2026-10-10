import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useToastsStore } from "./toasts";

describe("useToastsStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("push 展示提示并在 3.5 秒后自动消失", () => {
    const store = useToastsStore();

    store.push("已重新提交", "success");

    expect(store.items).toHaveLength(1);
    expect(store.items[0]).toMatchObject({
      message: "已重新提交",
      kind: "success",
    });

    vi.advanceTimersByTime(3500);
    expect(store.items).toHaveLength(0);
  });

  it("最多叠 3 条，最早的一条被挤出", () => {
    const store = useToastsStore();

    for (const message of ["一", "二", "三", "四"])
      store.push(message, "error");

    expect(store.items.map((item) => item.message)).toEqual(["二", "三", "四"]);
  });

  it("dismiss 手动关闭指定提示，到期定时器不再生效", () => {
    const store = useToastsStore();
    store.push("可关闭", "error");
    const id = store.items[0].id;

    store.dismiss(id);

    expect(store.items).toHaveLength(0);
    expect(() => vi.advanceTimersByTime(3500)).not.toThrow();
    expect(store.items).toHaveLength(0);
  });
});

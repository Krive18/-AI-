import { defineStore } from "pinia";
import { ref } from "vue";

export type ToastKind = "success" | "error";

export interface ToastItem {
  id: number;
  message: string;
  kind: ToastKind;
}

const MAX_TOASTS = 3;
const TOAST_TTL_MS = 3500;

let nextId = 1;

export const useToastsStore = defineStore("toasts", () => {
  const items = ref<ToastItem[]>([]);

  function dismiss(id: number) {
    items.value = items.value.filter((item) => item.id !== id);
  }

  function push(message: string, kind: ToastKind) {
    const toast: ToastItem = { id: nextId++, message, kind };
    items.value.push(toast);
    if (items.value.length > MAX_TOASTS) items.value.shift();
    setTimeout(() => dismiss(toast.id), TOAST_TTL_MS);
  }

  return { items, push, dismiss };
});

import { defineStore } from "pinia";
import { ref } from "vue";

export type ThemeMode = "dark" | "light";

const STORAGE_KEY = "ai-translation-theme";

function readStoredTheme(): ThemeMode | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function applyTheme(mode: ThemeMode) {
  document.documentElement.dataset.theme = mode;
}

/** Apply the persisted theme before the app mounts to avoid a flash. */
export function applyInitialTheme(): ThemeMode {
  const mode = readStoredTheme() ?? "dark";
  applyTheme(mode);
  return mode;
}

export const useThemeStore = defineStore("theme", () => {
  const mode = ref<ThemeMode>(readStoredTheme() ?? "dark");
  applyTheme(mode.value);

  function set(next: ThemeMode) {
    mode.value = next;
    applyTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage may be unavailable; the in-memory theme still applies.
    }
  }

  function toggle() {
    set(mode.value === "dark" ? "light" : "dark");
  }

  return { mode, set, toggle };
});

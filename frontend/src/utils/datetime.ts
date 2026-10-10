const pad = (value: number) => String(value).padStart(2, "0");

/** Backend timestamps are UTC without an offset suffix; parse as UTC, display in local time. */
function parseUtc(value: string): Date | null {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized.endsWith("Z") ? normalized : `${normalized}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = parseUtc(value);
  if (!date) return value.replace("T", " ").slice(0, 19);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = parseUtc(value);
  if (!date) return value.replace("T", " ").slice(0, 10);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

import { apiFetch } from "@/services/http";
import type { Account } from "@/types/api";

export interface AccountsResponse {
  items: Account[];
  nextCursor: number | null;
}
export interface TemporaryPasswordResponse {
  account: Account;
  temporaryPassword: string;
}

export function listAccounts(cursor?: number) {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", String(cursor));
  return apiFetch<AccountsResponse>(`/api/v1/admin/accounts?${query}`);
}

export function createAccount(payload: {
  loginName: string;
  displayName: string;
  role: 1 | 9;
}) {
  return apiFetch<TemporaryPasswordResponse>("/api/v1/admin/accounts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAccount(
  account: Account,
  changes: Partial<Pick<Account, "displayName" | "role" | "status">>,
) {
  return apiFetch<{ account: Account }>(
    `/api/v1/admin/accounts/${account.publicId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ version: account.version, ...changes }),
    },
  );
}

export function resetAccountPassword(account: Account) {
  return apiFetch<TemporaryPasswordResponse>(
    `/api/v1/admin/accounts/${account.publicId}/reset-password`,
    { method: "POST", body: JSON.stringify({ version: account.version }) },
  );
}

export function revokeAccountSessions(account: Account) {
  return apiFetch<{ account: Account }>(
    `/api/v1/admin/accounts/${account.publicId}/sessions/revoke`,
    { method: "POST", body: JSON.stringify({ version: account.version }) },
  );
}

export function setVideogenPermission(account: Account, enabled: boolean) {
  return apiFetch<{ account: Account }>(
    `/api/v1/admin/accounts/${account.publicId}/videogen-permission`,
    {
      method: "POST",
      body: JSON.stringify({ version: account.version, enabled }),
    },
  );
}

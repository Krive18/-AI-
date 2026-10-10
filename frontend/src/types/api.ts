export type Role = 1 | 9;
export type AccountStatus = 1 | 2;

export interface Account {
  publicId: string;
  loginName: string;
  displayName: string;
  role: Role;
  status: AccountStatus;
  mustChangePassword: boolean;
  videogenEnabled?: boolean;
  version?: number;
  createdAt?: string;
}

export interface AuthPayload {
  account: Account;
  csrfToken: string;
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    requestId: string;
    details: Record<string, unknown>;
  };
}

export interface AccountPage {
  data: Account[];
  pagination: { nextCursor: string | null; pageSize: number };
}

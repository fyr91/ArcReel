export type AccountRole = "admin" | "user";

export type AccountCreateInput = {
  username: unknown;
  password: unknown;
  displayName?: unknown;
  role?: unknown;
};

export type AccountProfile = {
  id: string;
  username: string;
  auth_email: string;
  display_name: string | null;
  role: AccountRole;
  status: "active" | "disabled";
  created_at: string;
  updated_at: string;
  creation_request_id: string | null;
  creation_request_fingerprint: string | null;
};

type NewAccountProfile = Omit<AccountProfile, "created_at" | "updated_at">;

export type AccountCreationStore = {
  findByRequestId: (requestId: string) => Promise<AccountProfile | null>;
  findByUsername: (username: string) => Promise<AccountProfile | null>;
  createAuthUser: (input: {
    email: string;
    password: string;
    appMetadata: Record<string, unknown>;
  }) => Promise<{ id: string }>;
  insertProfile: (profile: NewAccountProfile) => Promise<AccountProfile>;
  deleteAuthUser: (userId: string) => Promise<void>;
};

export class AccountCreateError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
    this.name = "AccountCreateError";
  }
}

export async function createAccountOperation(
  rawInput: AccountCreateInput,
  rawRequestId: string | null,
  integrationSecret: string,
  store: AccountCreationStore,
) {
  const input = normalizeInput(rawInput);
  const requestId = normalizeRequestId(rawRequestId);
  const fingerprint = requestId ? await requestFingerprint(input, integrationSecret) : null;

  if (requestId) {
    const replay = await store.findByRequestId(requestId);
    if (replay) {
      if (!fingerprint || replay.creation_request_fingerprint !== fingerprint) {
        throw new AccountCreateError(
          409,
          "IDEMPOTENCY_KEY_REUSED",
          "该创建请求已绑定其他账号内容，请关闭窗口后重新创建",
        );
      }
      return { account: publicProfile(replay), replayed: true };
    }
  }

  if (await store.findByUsername(input.username)) {
    throw new AccountCreateError(409, "USERNAME_EXISTS", "账号已存在");
  }

  const authEmail = `${input.username.toLowerCase()}@accounts.arcreel.invalid`;
  let authUser: { id: string };
  try {
    authUser = await store.createAuthUser({
      email: authEmail,
      password: input.password,
      appMetadata: { application: "arcreel" },
    });
  } catch {
    throw new AccountCreateError(400, "ACCOUNT_CREATE_FAILED", "账号创建失败");
  }

  try {
    const profile = await store.insertProfile({
      id: authUser.id,
      username: input.username,
      auth_email: authEmail,
      display_name: input.displayName,
      role: input.role,
      status: "active",
      creation_request_id: requestId,
      creation_request_fingerprint: fingerprint,
    });
    return { account: publicProfile(profile), replayed: false };
  } catch (error) {
    await store.deleteAuthUser(authUser.id);
    throw error;
  }
}

function normalizeInput(input: AccountCreateInput) {
  const username = String(input.username ?? "").trim();
  const password = String(input.password ?? "");
  const displayName = optional(input.displayName);
  const role = String(input.role || "user");
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/.test(username)) {
    throw new AccountCreateError(400, "USERNAME_INVALID", "账号需为 2-64 位字母、数字、点、下划线或短横线");
  }
  if (password.length < 8) {
    throw new AccountCreateError(400, "PASSWORD_WEAK", "初始密码至少 8 位");
  }
  if (role !== "admin" && role !== "user") {
    throw new AccountCreateError(400, "ROLE_INVALID", "角色无效");
  }
  return { username, password, displayName, role: role as AccountRole };
}

function normalizeRequestId(value: string | null) {
  if (!value) return null;
  const requestId = value.trim().toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(requestId)) {
    throw new AccountCreateError(400, "IDEMPOTENCY_KEY_INVALID", "创建请求标识无效");
  }
  return requestId;
}

async function requestFingerprint(
  input: { username: string; password: string; displayName: string | null; role: AccountRole },
  secret: string,
) {
  if (!secret) throw new Error("integration secret is required for idempotent account creation");
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const payload = JSON.stringify({
    username: input.username.toLowerCase(),
    password: input.password,
    display_name: input.displayName,
    role: input.role,
  });
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload)));
  return [...signature].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function publicProfile(profile: AccountProfile) {
  return {
    id: profile.id,
    username: profile.username,
    display_name: profile.display_name,
    role: profile.role,
    status: profile.status,
    created_at: profile.created_at,
    updated_at: profile.updated_at,
  };
}

function optional(value: unknown) {
  const text = String(value ?? "").trim();
  return text || null;
}

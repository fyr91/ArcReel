import {
  AccountCreateError,
  createAccountOperation,
  type AccountCreationStore,
  type AccountProfile,
} from "./account-creation.ts";

const requestId = "d070a5e6-4c2c-48cb-9cd9-0d606e0862b6";
const input = {
  username: "company.demo",
  password: "StrongPassword!123",
  displayName: "演示账号",
  role: "user" as const,
};

Deno.test("同一创建请求重放时返回原账号且不会再次创建 Auth 用户", async () => {
  const fixture = accountStore();

  const first = await createAccountOperation(input, requestId, "integration-secret", fixture.store);
  const replay = await createAccountOperation(input, requestId, "integration-secret", fixture.store);

  if (first.replayed || !replay.replayed) throw new Error("创建与重放状态不正确");
  if (first.account.id !== replay.account.id) throw new Error("重放没有返回同一账号");
  if (fixture.authCreateCalls() !== 1) throw new Error("重放重复创建了 Auth 用户");
});

Deno.test("同一幂等键绑定不同创建内容时拒绝复用", async () => {
  const fixture = accountStore();
  await createAccountOperation(input, requestId, "integration-secret", fixture.store);

  let captured: unknown;
  try {
    await createAccountOperation({ ...input, role: "admin" }, requestId, "integration-secret", fixture.store);
  } catch (error) {
    captured = error;
  }

  if (!(captured instanceof AccountCreateError) || captured.code !== "IDEMPOTENCY_KEY_REUSED") {
    throw new Error("幂等键复用没有被明确拒绝");
  }
  if (fixture.authCreateCalls() !== 1) throw new Error("无效重放触发了 Auth 写入");
});

Deno.test("不同创建请求使用已有用户名时仍返回用户名冲突", async () => {
  const fixture = accountStore();
  await createAccountOperation(input, requestId, "integration-secret", fixture.store);

  let captured: unknown;
  try {
    await createAccountOperation(
      input,
      "427065aa-01ae-49f0-a6b2-ea4a7a85fd08",
      "integration-secret",
      fixture.store,
    );
  } catch (error) {
    captured = error;
  }

  if (!(captured instanceof AccountCreateError) || captured.code !== "USERNAME_EXISTS") {
    throw new Error("普通用户名冲突语义被幂等逻辑破坏");
  }
});

function accountStore() {
  const profiles: AccountProfile[] = [];
  let authCreateCalls = 0;
  const store: AccountCreationStore = {
    findByRequestId: (id) => Promise.resolve(profiles.find((profile) => profile.creation_request_id === id) ?? null),
    findByUsername: (username) => Promise.resolve(
      profiles.find((profile) => profile.username.toLowerCase() === username.toLowerCase()) ?? null,
    ),
    createAuthUser: () => {
      authCreateCalls += 1;
      return Promise.resolve({ id: "5417366e-e48c-46f4-a94b-dacaf98b0b8f" });
    },
    insertProfile: (profile) => {
      const saved: AccountProfile = {
        ...profile,
        created_at: "2026-08-29T14:00:00.000Z",
        updated_at: "2026-08-29T14:00:00.000Z",
      };
      profiles.push(saved);
      return Promise.resolve(saved);
    },
    deleteAuthUser: () => Promise.resolve(),
  };
  return { store, authCreateCalls: () => authCreateCalls };
}

import { beforeEach, describe, expect, it, vi } from "vitest";

type ResponseFn = (response: Response, request: Request) => Response;

async function setup(provider = "local") {
  vi.resetModules();
  const { registerSessionGuard } = await import("./sessionGuard");
  const fns: ResponseFn[] = [];
  const client = { interceptors: { response: { use: (fn: ResponseFn) => fns.push(fn) } } };
  const logout = vi.fn(async () => {});
  registerSessionGuard(client as never, { provider, logout });
  const run = (status: number, auth?: string) =>
    fns.forEach((fn) =>
      fn(new Response(null, { status }), new Request("http://api/x", { headers: auth ? { Authorization: auth } : {} })),
    );
  return { fns, logout, run };
}

describe("registerSessionGuard", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("logs out once on a 401 for an authenticated request", async () => {
    const { logout, run } = await setup();
    run(401, "Bearer stale");
    run(401, "Bearer stale");
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("ignores other statuses and unauthenticated requests", async () => {
    const { logout, run } = await setup();
    run(403, "Bearer ok");
    run(503, "Bearer ok");
    run(401);
    expect(logout).not.toHaveBeenCalled();
  });

  it("does nothing for the Stack (cloud) provider", async () => {
    const { fns } = await setup("stack");
    expect(fns).toHaveLength(0);
  });
});

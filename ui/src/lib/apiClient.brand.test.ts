import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveBrowserBackendUrl } from "./apiClient";

describe("browser backend URL (OxeePhone same origin)", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("keeps the page origin even when the backend reports another address", () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "");
    expect(resolveBrowserBackendUrl("http://sngi-ai-phone-01.nb.us:8000")).toBe(window.location.origin);
  });

  it("still honours an explicit NEXT_PUBLIC_BACKEND_URL", () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://api.example.com");
    expect(resolveBrowserBackendUrl("http://sngi-ai-phone-01.nb.us:8000")).toBe("https://api.example.com");
  });
});

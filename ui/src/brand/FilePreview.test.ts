import { describe, expect, it } from "vitest";

import { hasPreview } from "./FilePreview";

describe("file preview", () => {
  it("covers text files and documents kept whole", () => {
    expect(hasPreview("Procédures.MD")).toBe(true);
    expect(hasPreview("notes.txt", "chunked")).toBe(true);
    expect(hasPreview("tarifs.pdf", "full_document")).toBe(true);
    expect(hasPreview("tarifs.pdf", "chunked")).toBe(false);
  });
});

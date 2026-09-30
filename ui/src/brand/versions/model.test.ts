import { describe, expect, it } from "vitest";

import { countsLabel, formatValue, originLabel, personLabel, summaryLanguage } from "./model";

describe("versions model", () => {
  it("labels the origin of a version", () => {
    expect(originLabel({ origin: null, api_key_prefix: null, restored_from: null })).toBeNull();
    expect(originLabel({ origin: "editor", api_key_prefix: null, restored_from: null })).toBe("Editor");
    expect(originLabel({ origin: "api", api_key_prefix: "dgr__bMZ", restored_from: null })).toBe("API key dgr__bMZ…");
    expect(originLabel({ origin: "restore", api_key_prefix: null, restored_from: 3 })).toBe("Restore of v3");
  });

  it("formats values and counts", () => {
    expect(formatValue(true)).toBe("on");
    expect(formatValue(null)).toBe("—");
    expect(formatValue({ a: 1 })).toBe('{ "a": 1 }');
    expect(countsLabel({ added: 1, removed: 0, changed: 2 })).toBe("+1 ~2");
    expect(personLabel({ id: 4, email: null })).toBe("user #4");
  });

  it("picks the summary language from the locale", () => {
    expect(summaryLanguage("fr-FR")).toBe("French");
    expect(summaryLanguage("en-US")).toBe("English");
    expect(summaryLanguage(undefined)).toBe("English");
  });
});

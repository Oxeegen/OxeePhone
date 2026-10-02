import { describe, expect, it } from "vitest";

import { estimateMinutes, formatDelta, formatIndicator, ms, parseNumbers, pct, rangeLabel, seconds, versionLabel } from "./model";

describe("test campaign formatting", () => {
  it("formats rates, durations and deltas", () => {
    expect(pct(0.756)).toBe("76 %");
    expect(pct(null)).toBe("—");
    expect(ms(850)).toBe("850 ms");
    expect(ms(1530)).toBe("1.53 s");
    expect(seconds(95)).toBe("1 min 35");
    expect(seconds(42)).toBe("42 s");
    expect(formatIndicator("score", 3.456)).toBe("3.46");
    expect(formatDelta("rate", 0.25)).toBe("+25 pts");
    expect(formatDelta("ms", -300)).toBe("−300 ms");
    expect(formatDelta("number", 0)).toBe("=");
    expect(formatDelta("number", null)).toBe("");
  });

  it("labels ranges and versions", () => {
    expect(rangeLabel([2, 2])).toBe("2");
    expect(rangeLabel([1, 4])).toBe("1–4");
    expect(versionLabel({ version_number: 5, version_status: "draft" })).toBe("v5 (draft)");
    expect(versionLabel({ version_number: 4, version_status: "published" })).toBe("v4");
  });

  it("parses a pool of numbers", () => {
    expect(parseNumbers("+33601\n+33602, +33601;;\n ")).toEqual(["+33601", "+33602"]);
  });

  it("estimates the duration", () => {
    expect(estimateMinutes(30, "phone", 3)).toBe(25);
    expect(estimateMinutes(10, "text", 3)).toBe(10);
  });
});

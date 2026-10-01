import { describe, expect, it } from "vitest";

import { type Fix, fixability, fixForFinding, operationLabel, priorFix, stepIndex } from "./model";

const fix = (id: string, findingId: string, status: Fix["status"], created_at: string) =>
  ({ id, finding: { id: findingId }, status, created_at }) as unknown as Fix;

describe("fixes model", () => {
  it("mirrors the API fixability", () => {
    expect(fixability({ rule: "reply_latency", category: "latency" }).fixable).toBe(false);
    expect(fixability({ rule: "stage_llm", category: "latency" }).fixable).toBe(false);
    expect(fixability({ rule: null, category: "tools" }).fixable).toBe(false);
    expect(fixability({ rule: "ping_pong", category: "routing" }).fixable).toBe(true);
    expect(fixability({ rule: null, category: "conversation" }).fixable).toBe(true);
  });

  it("shows the latest live fix of a finding", () => {
    const list = [fix("a", "r1", "discarded", "2026-10-01T10:00"), fix("b", "r1", "applied", "2026-10-01T09:00"), fix("c", "r2", "proposed", "2026-10-01T11:00")];
    expect(fixForFinding(list, "r1")?.id).toBe("b");
    expect(fixForFinding([list[0]], "r1")?.id).toBe("a");
    expect(fixForFinding(list, "r3")).toBeUndefined();
  });

  it("labels operations and steps", () => {
    expect(operationLabel({ op: "set_setting", key: "speaking_plan.stop.num_words", value: 2 })).toBe("Setting speaking_plan.stop.num_words = 2");
    expect(operationLabel({ op: "set_edge_field", from: "A", to: "B", field: "condition" })).toBe("Transition A → B › condition");
    expect(stepIndex("proposed")).toBe(0);
    expect(stepIndex("testing")).toBe(2);
    expect(stepIndex("published")).toBe(3);
  });
});

describe("prior fixes", () => {
  const published = {
    id: "p",
    report_id: "old",
    status: "published",
    updated_at: "2026-10-01T10:00",
    finding: { id: "r6", rule: "dead_air_caller", agent: "Accueil cabinet Martin", node: null },
  } as unknown as Fix;
  const finding = { id: "r2", rule: "dead_air_caller", agent: "Accueil cabinet Martin", node: null };

  it("finds a published fix of the same problem in another report", () => {
    expect(priorFix([published], finding, "new")?.id).toBe("p");
  });

  it("ignores the same report, other agents, drafts and model findings", () => {
    expect(priorFix([published], finding, "old")).toBeUndefined();
    expect(priorFix([published], { ...finding, agent: "Other" }, "new")).toBeUndefined();
    expect(priorFix([{ ...published, status: "applied" } as Fix], finding, "new")).toBeUndefined();
    expect(priorFix([published], { ...finding, rule: null }, "new")).toBeUndefined();
  });
});

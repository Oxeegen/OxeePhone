import { describe, expect, it } from "vitest";

import { DEFAULT_SPEAKING_PLAN, speakingPlanConfig, speakingPlanFrom } from "./SpeakingPlanSection";

describe("speaking plan", () => {
  it("derives a plan from the upstream turn settings", () => {
    const plan = speakingPlanFrom({ turn_stop_strategy: "turn_analyzer", turn_start_strategy: "min_words", turn_start_min_words: 4 });
    expect(plan.start.smart_endpointing).toBe("smart_turn");
    expect(plan.stop.num_words).toBe(4);
    expect(speakingPlanFrom({}).stop.num_words).toBe(0);
  });

  it("completes a stored plan with the defaults", () => {
    const plan = speakingPlanFrom({ speaking_plan: { start: { wait_seconds: 0.8 } } });
    expect(plan.start.wait_seconds).toBe(0.8);
    expect(plan.stop).toEqual(DEFAULT_SPEAKING_PLAN.stop);
  });

  it("keeps the upstream settings in line when saving", () => {
    const config = speakingPlanConfig({ ...DEFAULT_SPEAKING_PLAN, stop: { ...DEFAULT_SPEAKING_PLAN.stop, num_words: 2 } });
    expect(config).toMatchObject({ turn_start_strategy: "min_words", turn_start_min_words: 2, turn_stop_strategy: "transcription" });
    expect(speakingPlanConfig(DEFAULT_SPEAKING_PLAN).turn_start_strategy).toBe("default");
  });
});

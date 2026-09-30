import { describe, expect, it } from "vitest";

import run10 from "./__fixtures__/run10.json";
import graphs from "./__fixtures__/run10-routing.json";
import { type CallRun, recordingAnchor } from "./model";
import { buildRouting, type RoutingGraphs, transitionToolCallIds } from "./routing";

// A real call on the "Cabinet Martin — routage" agent:
// Accueil → Prise de rendez-vous → Fin d'appel (scrubbed).
const run = run10 as unknown as CallRun;
const data = graphs as unknown as RoutingGraphs;

describe("routing", () => {
  const model = buildRouting(run, data, recordingAnchor(run));

  it("follows the path through the graph", () => {
    expect(model.steps.map((s) => s.nodeName)).toEqual(["Accueil", "Prise de rendez-vous", "Fin d'appel"]);
    expect(model.steps[0].cause).toBe("start");
  });

  it("recovers the edge and condition from the LLM's transition tool call", () => {
    const toBooking = model.steps[1];
    expect(toBooking.cause).toBe("condition");
    expect(toBooking.toolName).toBe("prise_de_rendez_vous");
    expect(toBooking.edge?.condition).toContain("rendez-vous");
    expect(toBooking.trigger).toContain("rendez-vous");
    const toEnd = model.steps[2];
    expect(toEnd.toolName).toBe("rendez_vous_confirm_");
    expect(toEnd.edge?.label).toBe("Rendez-vous confirmé");
    expect(toEnd.edge?.transition_speech).toBe("Parfait, c'est noté.");
  });

  it("measures time spent in each node", () => {
    expect(model.steps[1].durationSecs).toBeGreaterThan(20);
    expect(model.steps.every((s) => s.durationSecs !== null)).toBe(true);
  });

  it("explains how the call ended", () => {
    expect(model.ending.status).toBe("end_call");
    expect(model.ending.description).toBe("Reached the end node “Fin d'appel”");
  });

  it("identifies transition tool calls to hide them from tool cards", () => {
    const ids = transitionToolCallIds(run, model);
    expect(ids.size).toBe(2);
  });

  it("degrades gracefully without the graph", () => {
    const bare = buildRouting(run, null, recordingAnchor(run));
    expect(bare.steps.map((s) => s.nodeName)).toEqual(["Accueil", "Prise de rendez-vous", "Fin d'appel"]);
    expect(bare.steps[1].cause).toBe("unmatched");
  });
});

describe("handoff to another agent", () => {
  it("splits the route per agent and explains the handoff", () => {
    const base = run.logs!.realtime_feedback_events!;
    const last = Date.parse(base.at(-1)!.timestamp!);
    const at = (s: number) => new Date(last + s * 1000).toISOString();
    const handoffRun: CallRun = {
      ...run,
      gathered_context: {
        ...run.gathered_context,
        agent_visits: [
          { visit_id: "v1", workflow_id: 3, workflow_name: "Cabinet Martin — routage", definition_id: 4, entered_at: Date.parse(base[0].timestamp!) / 1000, exited_at: last / 1000 + 1, exit_reason: "transferred" },
          { visit_id: "v2", workflow_id: 9, workflow_name: "Facturation", definition_id: 99, entered_at: last / 1000 + 2, exited_at: last / 1000 + 20, exit_reason: "end_call" },
        ],
        agent_transfers: [{ outcome: "completed", destination_workflow_id: 9, destination_label: "Transfert facturation" }],
      },
      logs: {
        realtime_feedback_events: [
          ...base,
          { type: "rtf-node-transition", timestamp: at(3), payload: { node_id: "1", node_name: "Accueil facturation", previous_node_id: null, previous_node_name: null } },
        ],
      },
    };
    const model = buildRouting(handoffRun, data, recordingAnchor(handoffRun));
    const handoff = model.steps.at(-1)!;
    expect(handoff.visitIndex).toBe(1);
    expect(handoff.cause).toBe("handoff");
    expect(handoff.handoffLabel).toBe("Transfert facturation");
    expect(model.steps.filter((s) => s.visitIndex === 0)).toHaveLength(3);
  });
});

"""Replay recorded calls, as text, against a given version of an agent.

Used to test an automatic fix before publishing it: the caller's turns of a
real call are sent one by one to the agent pinned on a version (the published
one, then the draft), through upstream's text-chat engine
(``execute_text_chat_pending_turn``), and the paths are compared.

Safety:
- tools are never executed: HTTP / MCP tool handlers ask ``tool_override``
  first (gated hook in ``pipecat_engine_custom_tools.py``), which answers with
  the result recorded in the source call for the same tool, in order, or with
  a neutral "simulated" result;
- the text session is kept in memory and completion tasks (post-call
  webhooks, integrations, QA) are never enqueued; the run row only exists
  because the engine pins its definition there. Simulation runs are named
  ``OXEE-SIM-…`` and left out of reports, analyses and version call counts.

Limit: the replay is open loop. The caller says what the real caller said,
even when the agent answers differently; cases where the conversation diverges
early are reported as such.
"""

from __future__ import annotations

import contextvars
import copy
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.brand.db import SIM_RUN_PREFIX  # noqa: E402  (one prefix for queries and runs)

MAX_TURNS = 20

# --- Tool interception --------------------------------------------------------

_tool_results: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "oxee_simulation_tools", default=None
)


def tool_override(function_name: str, arguments: dict | None) -> dict | None:
    """Result to use instead of executing a tool, or None outside a simulation."""
    state = _tool_results.get()
    if state is None:
        return None
    recorded = state["recorded"].get(function_name)
    state["calls"].append({"name": function_name, "arguments": arguments or {}})
    if recorded:
        result = recorded.popleft()
        recorded.append(result)  # keep answering if the agent calls it more often
        return result
    return {
        "status": "simulated",
        "note": "Simulation: this tool was not executed. Assume it succeeded and "
        "continue the conversation.",
    }


def recorded_tool_results(events: list[dict]) -> dict[str, deque]:
    results: dict[str, deque] = defaultdict(deque)
    for e in events:
        if e.get("type") == "rtf-function-call-end":
            p = e.get("payload") or {}
            if p.get("function_name") and p.get("result") is not None:
                results[str(p["function_name"])].append(p["result"])
    return results


# --- Source calls ---------------------------------------------------------------


def caller_script(events: list[dict]) -> list[str]:
    """The caller's turns of a recorded call (consecutive utterances merged)."""
    turns: list[str] = []
    last_role = None
    for e in events:
        etype, p = e.get("type"), e.get("payload") or {}
        if etype == "rtf-user-transcription":
            if p.get("final") is False:
                continue
            text = str(p.get("text") or "").strip()
            if not text:
                continue
            if last_role == "caller" and turns:
                turns[-1] = f"{turns[-1]} {text}"
            else:
                turns.append(text)
            last_role = "caller"
        elif etype == "rtf-bot-text" and str(p.get("text") or "").strip():
            last_role = "agent"
    return turns[:MAX_TURNS]


def recorded_path(events: list[dict]) -> list[str]:
    path = []
    for e in events:
        if e.get("type") == "rtf-node-transition":
            name = (e.get("payload") or {}).get("node_name")
            if name and (not path or path[-1] != name):
                path.append(name)
    return path


# --- Replay ---------------------------------------------------------------------


def _session_path(turns: list[dict]) -> list[str]:
    path = []
    for t in turns:
        for e in t.get("events") or []:
            if e.get("type") == "node_transition":
                name = (e.get("payload") or {}).get("node_name")
                if name and (not path or path[-1] != name):
                    path.append(name)
    return path


async def replay(
    *,
    workflow_id: int,
    definition_id: int,
    use_draft: bool,
    user_id: int,
    organization_id: int,
    script: list[str],
    tool_results: dict[str, deque],
    label: str,
) -> dict:
    """Run ``script`` against one version; returns the transcript and path."""
    from api.db import db_client
    from api.enums import WorkflowRunMode, WorkflowRunState
    from api.services.workflow.text_chat_logs import (
        build_text_chat_realtime_feedback_events,
    )
    from api.services.workflow.text_chat_runner import (
        default_text_chat_checkpoint,
        execute_text_chat_pending_turn,
    )
    from api.services.workflow.text_chat_session_service import (
        build_pending_text_chat_turn,
        default_text_chat_session_data,
    )

    run = await db_client.create_workflow_run(
        name=f"{SIM_RUN_PREFIX}{label}"[:250],
        workflow_id=workflow_id,
        mode=WorkflowRunMode.TEXTCHAT.value,
        user_id=user_id,
        initial_context={},
        organization_id=organization_id,
        definition_id=definition_id,
        use_draft=use_draft,
    )
    await db_client.update_workflow_run(
        run.id, annotations={"oxee_simulation": {"label": label}}
    )

    session = default_text_chat_session_data()
    checkpoint = default_text_chat_checkpoint()
    state = {"recorded": copy.deepcopy(tool_results), "calls": []}
    token = _tool_results.set(state)
    transcript: list[dict] = []
    ended = False
    error = None
    current_node = None
    pending: list[str | None] = [None, *script]  # None: the agent opens
    try:
        for user_text in pending:
            if ended:
                break
            turn = build_pending_text_chat_turn(user_text=user_text)
            session["turns"] = [*session["turns"], turn]
            if user_text is not None:
                transcript.append({"role": "caller", "text": user_text})
            result = await execute_text_chat_pending_turn(
                workflow_run_id=run.id,
                workflow_id=workflow_id,
                session_data=session,
                checkpoint=checkpoint,
            )
            turn.update(
                status="completed",
                assistant_message=(
                    {
                        "text": result.assistant_text,
                        "created_at": result.assistant_created_at,
                    }
                    if result.assistant_text
                    else None
                ),
                events=result.events,
                usage=result.usage,
                checkpoint_after_turn=result.checkpoint,
            )
            checkpoint = result.checkpoint
            names = [
                (e.get("payload") or {}).get("node_name")
                for e in result.events
                if e.get("type") == "node_transition"
            ]
            for name in names:
                if name and name != current_node:
                    current_node = name
                    transcript.append(
                        {"role": "system", "text": f"→ {name}", "node": name}
                    )
            if result.assistant_text:
                transcript.append(
                    {
                        "role": "agent",
                        "text": result.assistant_text,
                        "node": current_node,
                    }
                )
            ended = result.is_completed
    except Exception as e:  # a broken draft must show as a failed case
        logger.warning(f"Simulation {label} failed: {e}")
        error = str(e)
    finally:
        _tool_results.reset(token)
        try:
            await db_client.update_workflow_run(
                run.id,
                is_completed=True,
                state=WorkflowRunState.COMPLETED.value,
                logs={
                    "realtime_feedback_events": build_text_chat_realtime_feedback_events(
                        session
                    )
                },
                gathered_context={"call_status": "simulation"},
            )
        except Exception as e:
            logger.warning(f"Could not close simulation run {run.id}: {e}")

    return {
        "run_id": run.id,
        "path": _session_path(session["turns"]),
        "transcript": transcript,
        "tool_calls": state["calls"],
        "ended": ended,
        "caller_turns_used": sum(1 for t in transcript if t["role"] == "caller"),
        "error": error,
        "at": datetime.now(UTC).isoformat(),
    }


# --- Path metrics -----------------------------------------------------------------


def path_metrics(path: list[str], transcript: list[dict]) -> dict:
    """Deterministic facts to compare two replays."""
    revisits = sum(max(0, n - 1) for n in _counts(path).values())
    ping_pong = sum(1 for i in range(2, len(path)) if path[i] == path[i - 2])
    per_node: dict[str, int] = defaultdict(int)
    for m in transcript:
        if m["role"] == "agent" and m.get("node"):
            per_node[m["node"]] += 1
    return {
        "steps": len(path),
        "revisits": revisits,
        "ping_pong": ping_pong,
        "max_replies_in_a_node": max(per_node.values(), default=0),
        "agent_replies": sum(1 for m in transcript if m["role"] == "agent"),
    }


def _counts(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for i in items:
        out[i] += 1
    return out

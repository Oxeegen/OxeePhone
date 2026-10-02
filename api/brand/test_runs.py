"""Executions of test campaigns: play, judge, report, compare.

An execution plays every enabled scenario of a campaign (``passes`` times
each) against ONE version of the agent (published, draft or an older one):

    phone   the tester agent calls the agent's number through the tester's
            telephony configuration (Asterisk / any Dograh provider). The
            agent side runs the version under test (test_calls.claim_inbound).
    text    the simulated caller and the agent exchange text through
            upstream's text-chat engine: no telephony, no audio, no latency.

Each call is then judged by the analysis model (goal, criteria, forbidden
behaviours, quality scores) and checked deterministically (end node, tools,
extracted variables), and measured from the agent run (latency per stage,
interruptions, tools, path through the graph). The report aggregates the
calls; two executions are compared indicator by indicator, scenario by
scenario, with the configuration diff between the two versions.

Storage: organization configurations ``OXEE_TESTEXEC:<id>``.
Calls of both sides are named ``OXEE-TEST-…`` and left out of the production
statistics and analyses.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.brand import db as brand_db
from api.brand import test_calls
from api.brand import test_campaigns as campaigns
from api.brand.analysis_thresholds import DEFAULTS as THRESHOLD_DEFAULTS
from api.brand.test_technical import call_technical, technical_report
from api.db import db_client

PREFIX = "OXEE_TESTEXEC:"
MAX_EXECUTIONS = 300
# One execution at a time per API process: calls hammer the models.
_EXECUTIONS = asyncio.Lock()
_CANCEL: set[str] = set()
MAX_TEXT_EXCHANGES = 30
END_TAG = "<END_CALL>"
POLL_SECONDS = 3.0
ANSWER_TIMEOUT = 90.0
CHANNELS = ("phone", "text")
VERDICTS = ("pass", "partial", "fail")


class ExecutionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def save(organization_id: int, execution: dict) -> dict:
    execution["updated_at"] = _now()
    await db_client.upsert_configuration(
        organization_id, PREFIX + execution["id"], execution
    )
    return execution


async def get(organization_id: int, execution_id: str) -> dict | None:
    row = await db_client.get_configuration(organization_id, PREFIX + execution_id)
    return dict(row.value) if row and row.value else None


async def list_executions(
    organization_id: int, *, campaign_id: str | None = None
) -> list[dict]:
    items = await brand_db.list_configurations_by_prefix(
        organization_id, PREFIX, limit=MAX_EXECUTIONS
    )
    if campaign_id:
        items = [e for e in items if e.get("campaign_id") == campaign_id]
    return items


async def delete(organization_id: int, execution_id: str) -> bool:
    return await brand_db.delete_configuration(organization_id, PREFIX + execution_id)


def stale(execution: dict) -> dict:
    """An execution left running by a restarted API is marked interrupted."""
    from datetime import timedelta

    if execution.get("status") in ("queued", "running") and execution.get("updated_at"):
        age = datetime.now(UTC) - datetime.fromisoformat(execution["updated_at"])
        if age > timedelta(minutes=20):
            return {
                **execution,
                "status": "interrupted",
                "error": "interrupted (the API restarted?)",
            }
    return execution


# --- Creation -------------------------------------------------------------------


async def resolve_version(organization_id: int, workflow_id: int, version: Any):
    """(definition, use_draft) for "published", "draft" or a definition id."""
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise ExecutionError("agent not found")
    if version in (None, "", "published"):
        if not workflow.released_definition_id:
            raise ExecutionError("the agent has no published version")
        definition = await brand_db.get_workflow_version(
            workflow_id, workflow.released_definition_id
        )
    elif version == "draft":
        definition = await db_client.get_draft_version(workflow_id)
        if definition is None:
            raise ExecutionError("the agent has no draft")
    else:
        definition = await brand_db.get_workflow_version(workflow_id, int(version))
        if definition is None:
            raise ExecutionError("version not found")
    return workflow, definition, definition.status == "draft"


async def phone_destination(organization_id: int, workflow_id: int) -> str:
    settings = await campaigns.get_settings(organization_id)
    if settings.get("test_inbound_number"):
        return settings["test_inbound_number"]
    numbers = await brand_db.agent_phone_numbers(organization_id, workflow_id)
    if not numbers:
        raise ExecutionError(
            "the agent has no inbound phone number (Telephony › Phone numbers), "
            "and no dedicated test number is set in the test settings"
        )
    return numbers[0]["address"]


async def check_phone_setup(organization_id: int, workflow_id: int) -> dict:
    """What a phone execution needs, or an error saying what is missing."""
    from api.services.telephony.factory import get_telephony_provider_by_id

    settings = await campaigns.get_settings(organization_id)
    config_id = settings.get("tester_telephony_configuration_id")
    if not config_id:
        raise ExecutionError(
            "choose the tester's telephony configuration in the test settings"
        )
    try:
        provider = await get_telephony_provider_by_id(config_id, organization_id)
    except Exception as e:
        raise ExecutionError(f"tester telephony configuration: {e}") from e
    if not provider.validate_config():
        raise ExecutionError("the tester's telephony configuration is incomplete")
    return {
        "telephony_configuration_id": config_id,
        "provider": provider.PROVIDER_NAME,
        "destination": await phone_destination(organization_id, workflow_id),
    }


def _snapshot(scenario: dict) -> dict:
    return {
        k: scenario.get(k)
        for k in (
            "id",
            "title",
            "intent",
            "levels",
            "speed",
            "voice",
            "caller_number",
            "persona",
            "goal",
            "behaviour",
            "facts",
            "criteria",
            "forbidden",
            "expected_end_node",
            "expected_variables",
            "expected_tools",
            "tool_hints",
            "variant_of",
        )
    }


async def _engine_snapshot(organization_id: int) -> dict:
    from api.brand import agent_tuning as tuning

    if not tuning_enabled():
        return {}
    return await tuning.get_engine_settings(organization_id)


def tuning_enabled() -> bool:
    from api.brand.config import BRAND

    return BRAND.agent_tuning


def _flat(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update({f"{k}.{kk}": vv for kk, vv in v.items()})
        else:
            out[k] = v
    return out


def engine_changes(a: dict | None, b: dict | None) -> list[dict]:
    """Platform settings that differ between two executions."""
    from api.brand import agent_tuning as tuning

    out = []
    for block in tuning.BLOCKS:
        ea = tuning.effective_block(block, a or {})
        eb = tuning.effective_block(block, b or {})
        flat_a, flat_b = _flat(ea), _flat(eb)
        for key in sorted(set(flat_a) | set(flat_b)):
            if flat_a.get(key) != flat_b.get(key):
                out.append(
                    {
                        "block": block,
                        "key": key,
                        "a": flat_a.get(key),
                        "b": flat_b.get(key),
                    }
                )
    return out


def _version_snapshot(definition: Any) -> dict:
    from api.brand.versions import _snapshot

    return _snapshot(definition)


async def create_execution(
    organization_id: int,
    user: Any,
    campaign: dict,
    *,
    version: Any,
    channel: str,
    passes: int,
    personas: str,
    concurrency: int | None,
    scenario_ids: list[str] | None = None,
) -> dict:
    from api.brand import versions

    if channel not in CHANNELS:
        raise ExecutionError(f"channel must be one of {', '.join(CHANNELS)}")
    if campaign.get("status") == "generating":
        raise ExecutionError("the scenarios are still being written")
    workflow, definition, use_draft = await resolve_version(
        organization_id, campaign["workflow_id"], version
    )
    scenarios = [
        s
        for s in campaign.get("scenarios") or []
        if s.get("enabled", True) and (not scenario_ids or s["id"] in scenario_ids)
    ]
    if not scenarios:
        raise ExecutionError("no enabled scenario to play")
    phone = (
        await check_phone_setup(organization_id, workflow.id)
        if channel == "phone"
        else None
    )
    settings = await campaigns.get_settings(organization_id)
    passes = max(1, min(10, int(passes or 1)))
    if personas == "fresh":
        scenarios = [dict(s, voice=None, caller_number=None) for s in scenarios]
        seed = random.randrange(1, 10**9)
        campaigns._assign_pools(scenarios, settings, seed)
        speeds = campaigns.draw_speeds(campaign["speed"], len(scenarios), seed)
        for s, speed in zip(scenarios, speeds):
            s["speed"] = speed
    calls, index = [], 0
    for p in range(1, passes + 1):
        for s in scenarios:
            index += 1
            calls.append(
                {
                    "index": index,
                    "pass": p,
                    "scenario_id": s["id"],
                    "scenario": _snapshot(s),
                    "status": "pending",
                }
            )
    execution = {
        "id": uuid.uuid4().hex[:12],
        "campaign_id": campaign["id"],
        "campaign_name": campaign["name"],
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "definition_id": definition.id,
        "version_number": definition.version_number,
        "version_status": definition.status,
        "use_draft": use_draft,
        "channel": channel,
        "phone": phone,
        "passes": passes,
        "personas": "fresh" if personas == "fresh" else "frozen",
        "concurrency": max(1, min(10, int(concurrency or settings["concurrency"]))),
        "tools_mode": campaign.get("tools_mode") or "simulated",
        "language": campaign.get("language") or "English",
        "max_duration_seconds": campaign.get("max_duration_seconds") or 300,
        "created_at": _now(),
        "created_by": {
            "id": getattr(user, "id", None),
            "email": getattr(user, "email", None),
        },
        "via": versions.current_channel().get("channel"),
        "status": "queued",
        "calls": calls,
        "report": None,
        # The version tested (masked like the versions page), kept for the
        # comparisons once a draft is discarded.
        "definition_snapshot": _version_snapshot(definition),
        # Platform call-engine settings in force (not versioned with the agent).
        "engine_snapshot": await _engine_snapshot(organization_id),
    }
    return await save(organization_id, execution)


def cancel(execution_id: str) -> None:
    _CANCEL.add(execution_id)


# --- Running --------------------------------------------------------------------


async def run(organization_id: int, execution_id: str, user_id: int) -> None:
    """Background: play, judge and report (one execution at a time)."""
    async with _EXECUTIONS:
        try:
            await _run(organization_id, execution_id, user_id)
        except Exception as e:
            logger.exception(f"Test execution {execution_id} failed: {e}")
            execution = await get(organization_id, execution_id)
            if execution:
                execution.update(status="failed", error=str(e), finished_at=_now())
                await save(organization_id, execution)
        finally:
            _CANCEL.discard(execution_id)


async def _run(organization_id: int, execution_id: str, user_id: int) -> None:
    from api.brand.analysis import _graph_index, resolve_analysis_model

    execution = await get(organization_id, execution_id)
    if execution is None:
        return
    if execution_id in _CANCEL:
        execution.update(status="cancelled", finished_at=_now())
        await save(organization_id, execution)
        return
    model = await resolve_analysis_model(organization_id)
    if not model:
        raise ExecutionError("no analysis model configured (Models › Analysis)")
    graphs = await brand_db.get_definition_graphs(
        [execution["definition_id"]], organization_id=organization_id
    )
    index = _graph_index(graphs).get(execution["definition_id"])
    definition = await brand_db.get_workflow_version(
        execution["workflow_id"], execution["definition_id"]
    )
    brief = campaigns.agent_brief(
        definition.workflow_json or {}, definition.workflow_configurations or {}
    )
    from api.brand.analysis_thresholds import load as load_thresholds

    context = {
        "thresholds": (await load_thresholds(organization_id))["values"],
        "organization_id": organization_id,
        "user_id": user_id,
        "model": model,
        "index": index,
        "brief": brief,
        "agent_name": execution["workflow_name"],
    }
    concurrency = execution["concurrency"]
    if execution["channel"] == "phone":
        from api.services.call_concurrency import call_concurrency

        context["tester_workflow_id"] = await campaigns.ensure_tester(
            organization_id, user_id
        )
        # Each test call holds two slots (caller and agent).
        limit = await call_concurrency.get_org_concurrent_limit(organization_id)
        concurrency = max(1, min(concurrency, limit // 2))
        # Paired by arrival order: one call at a time, or they could cross.
        if (await campaigns.get_settings(organization_id)).get(
            "pairing"
        ) == "arrival_order":
            concurrency = 1
    execution.update(status="running", started_at=_now(), error=None)
    await save(organization_id, execution)

    semaphore = asyncio.Semaphore(concurrency)

    async def one(call: dict) -> None:
        async with semaphore:
            if execution_id in _CANCEL:
                call["status"] = "cancelled"
                return
            call.update(status="running", started_at=_now())
            await save(organization_id, execution)
            try:
                if execution["channel"] == "text":
                    played = await _play_text(execution, call, context)
                else:
                    played = await _play_phone(execution, call, context)
                call.update(played)
                call["status"] = "judging"
                await save(organization_id, execution)
                await _evaluate(execution, call, context)
                call["status"] = "done"
            except Exception as e:
                logger.warning(
                    f"Test execution {execution_id} call {call['index']} failed: {e}"
                )
                call.update(status="error", error=str(e))
            call["finished_at"] = _now()
            await save(organization_id, execution)

    await asyncio.gather(*(one(c) for c in execution["calls"]))
    execution["report"] = aggregate(execution, index, context["thresholds"])
    execution.update(
        status="cancelled" if execution_id in _CANCEL else "done",
        finished_at=_now(),
    )
    await save(organization_id, execution)


def _test_context(execution: dict, call: dict) -> dict:
    scenario = call["scenario"]
    return {
        "execution": execution["id"],
        "call": call["index"],
        "tools_mode": execution["tools_mode"],
        "scenario": scenario.get("title"),
        "tool_hints": scenario.get("tool_hints"),
    }


# --- Text channel ---------------------------------------------------------------------

TEXT_RULES = f"""

This conversation is written, not spoken: each of your messages is exactly
what you say, nothing else. When you hang up, write your last words followed
by {END_TAG}."""


def _strip_end(text: str) -> tuple[str, bool]:
    ended = END_TAG in text
    return text.replace(END_TAG, "").strip().strip('"'), ended


async def _play_text(execution: dict, call: dict, ctx: dict) -> dict:
    from api.brand.llm import chat_messages
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

    scenario = call["scenario"]
    org = ctx["organization_id"]
    run = await db_client.create_workflow_run(
        name=test_calls.agent_run_name(execution["id"], call["index"]),
        workflow_id=execution["workflow_id"],
        mode=WorkflowRunMode.TEXTCHAT.value,
        user_id=ctx["user_id"],
        initial_context={
            "caller_number": scenario.get("caller_number") or "",
            "oxee_test": _test_context(execution, call),
        },
        organization_id=org,
        definition_id=execution["definition_id"],
        use_draft=execution["use_draft"],
    )
    system = (
        campaigns.tester_prompt(
            scenario, agent_name=ctx["agent_name"], language=execution["language"]
        )
        + TEXT_RULES
    )
    history: list[dict] = []
    session = default_text_chat_session_data()
    checkpoint = default_text_chat_checkpoint()
    gathered: dict = {}
    ended_by, error = "limit", None
    started = time.monotonic()
    user_text: str | None = None  # the agent opens
    caller_done = False
    try:
        for _ in range(MAX_TEXT_EXCHANGES):
            turn = build_pending_text_chat_turn(user_text=user_text)
            session["turns"] = [*session["turns"], turn]
            result = await execute_text_chat_pending_turn(
                workflow_run_id=run.id,
                workflow_id=execution["workflow_id"],
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
            gathered = result.gathered_context or gathered
            if result.assistant_text:
                history.append({"role": "user", "content": result.assistant_text})
            if result.is_completed:
                ended_by = "agent"
                break
            if caller_done:
                ended_by = "caller"
                break
            if execution["id"] in _CANCEL:
                ended_by = "cancelled"
                break
            reply = await chat_messages(
                ctx["model"],
                (
                    [{"role": "system", "content": system}, *history]
                    if history
                    else [
                        {"role": "system", "content": system},
                        {"role": "user", "content": "(the agent answers the phone)"},
                    ]
                ),
                max_tokens=400,
                temperature=0.8,
                timeout=90.0,
            )
            user_text, caller_done = _strip_end(reply)
            if not user_text:
                ended_by = "caller"
                break
            history.append({"role": "assistant", "content": user_text})
    except Exception as e:  # a broken version must show as a failed call
        logger.warning(f"Text test call {run.id} failed: {e}")
        error = str(e)
    finally:
        await db_client.update_workflow_run(
            run.id,
            is_completed=True,
            state=WorkflowRunState.COMPLETED.value,
            logs={
                "realtime_feedback_events": build_text_chat_realtime_feedback_events(
                    session
                )
            },
            gathered_context={
                **{k: v for k, v in gathered.items() if k == "extracted_variables"},
                "call_status": "error" if error else "completed",
                "oxee_test_ended_by": ended_by,
            },
            usage_info={"call_duration_seconds": round(time.monotonic() - started, 1)},
        )
    if error:
        raise ExecutionError(error)
    return {"agent_run_id": run.id, "ended_by": ended_by}


# --- Phone channel ----------------------------------------------------------------------


async def _play_phone(execution: dict, call: dict, ctx: dict) -> dict:
    from api.enums import CallType, WorkflowRunState
    from api.services.call_concurrency import call_concurrency
    from api.services.quota_service import authorize_workflow_run_start
    from api.services.telephony.factory import get_telephony_provider_by_id
    from api.services.workflow_run_failure import mark_workflow_run_failed
    from api.utils.common import get_backend_endpoints

    org = ctx["organization_id"]
    scenario = call["scenario"]
    phone = execution["phone"]
    destination = phone["destination"]
    token = test_calls.new_token()
    agent_name = test_calls.agent_run_name(execution["id"], call["index"])
    await test_calls.register_call(
        org,
        token,
        {
            "workflow_id": execution["workflow_id"],
            "definition_id": execution["definition_id"],
            "agent_run_name": agent_name,
            "test": _test_context(execution, call),
        },
    )
    tester_id = ctx["tester_workflow_id"]
    tester = await db_client.get_workflow(tester_id, organization_id=org)
    provider = await get_telephony_provider_by_id(
        phone["telephony_configuration_id"], org
    )
    voice = scenario.get("voice") or {}
    initial_context = {
        campaigns.TESTER_PROMPT_VAR: campaigns.tester_prompt(
            scenario, agent_name=ctx["agent_name"], language=execution["language"]
        ),
        "oxee_tester": {
            "voice": voice.get("id"),
            "speed": scenario.get("speed"),
            "impatience": (scenario.get("levels") or {}).get("impatience", 1),
            "max_duration": execution["max_duration_seconds"],
            "execution": execution["id"],
            "call": call["index"],
        },
        "phone_number": destination,
        "called_number": destination,
        "direction": "outbound",
        "provider": provider.PROVIDER_NAME,
        "telephony_configuration_id": phone["telephony_configuration_id"],
    }
    slot = await call_concurrency.acquire_org_slot(org, source="oxee_test", timeout=300)
    caller_run = None
    try:
        caller_run = await db_client.create_workflow_run(
            name=test_calls.caller_run_name(execution["id"], call["index"]),
            workflow_id=tester_id,
            mode=provider.PROVIDER_NAME,
            user_id=tester.user_id,
            call_type=CallType.OUTBOUND,
            initial_context=initial_context,
            organization_id=org,
            definition_id=tester.released_definition_id,
        )
        await call_concurrency.bind_workflow_run(slot, caller_run.id)
        quota = await authorize_workflow_run_start(
            workflow_id=tester_id,
            organization_id=org,
            workflow_run_id=caller_run.id,
        )
        if not quota.has_quota:
            raise ExecutionError(quota.error_message or "quota exceeded")
        backend, _ = await get_backend_endpoints()
        result = await provider.initiate_call(
            to_number=destination,
            webhook_url=f"{backend}/api/v1/telephony/{provider.WEBHOOK_ENDPOINT}"
            f"?workflow_id={tester_id}&workflow_run_id={caller_run.id}"
            f"&organization_id={org}",
            workflow_run_id=caller_run.id,
            from_number=test_calls.caller_id(
                token, scenario.get("caller_number") or "0000000000"
            ),
            workflow_id=tester_id,
            organization_id=org,
        )
        await db_client.update_workflow_run(
            run_id=caller_run.id,
            gathered_context={
                "provider": provider.PROVIDER_NAME,
                **(result.provider_metadata or {}),
            },
        )
    except Exception as e:
        await test_calls.forget_call(org, token)
        if caller_run is not None:
            await mark_workflow_run_failed(caller_run.id, f"Test call failed: {e}")
            await call_concurrency.release_workflow_run_slot(caller_run.id)
        else:
            await call_concurrency.release_slot(slot)
        raise

    started = time.monotonic()
    deadline = started + execution["max_duration_seconds"] + 180
    agent_run: dict | None = None
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            caller = await db_client.get_workflow_run(
                caller_run.id, organization_id=org
            )
            if agent_run is None or not agent_run.get("is_completed"):
                agent_run = (
                    await brand_db.find_run_by_name(org, agent_name) or agent_run
                )
            caller_done = bool(caller and caller.is_completed) or (
                caller is not None and caller.state == WorkflowRunState.COMPLETED.value
            )
            if agent_run is None and time.monotonic() - started > ANSWER_TIMEOUT:
                if caller_done:
                    status = (caller.gathered_context or {}).get("call_status")
                    raise ExecutionError(
                        f"the agent side of this test call was not found (caller "
                        f"side: {status or 'ended'}): either the agent did not "
                        "answer (dial plan), or it answered without recognizing "
                        "the test call because the CallerID name did not reach it "
                        "(Test settings › Pairing: arrival order)"
                    )
            if agent_run and agent_run.get("is_completed") and caller_done:
                break
        else:
            raise ExecutionError("the call did not end in time")
    finally:
        await test_calls.forget_call(org, token)
    # Logs are written when the pipeline closes: give them a moment.
    for _ in range(10):
        if (agent_run.get("logs") or {}).get("realtime_feedback_events"):
            break
        await asyncio.sleep(2)
        agent_run = await brand_db.find_run_by_name(org, agent_name) or agent_run
    return {
        "agent_run_id": agent_run["id"],
        "caller_run_id": caller_run.id,
        "ended_by": (agent_run.get("gathered_context") or {}).get("call_status"),
    }


# --- Evaluation -----------------------------------------------------------------------

JUDGE_PROMPT = """You judge a TEST call between a simulated caller and a phone
voice agent. You receive the scenario the caller played (goal, success
criteria, forbidden behaviours), the agent's configuration (nodes and
transitions), the transcript with the agent's node for each reply and the tool
calls, the variables the agent extracted and how the call ended.

Judge the AGENT, not the caller:
- "goal_reached": did the caller get what the scenario's goal says, as far as
  the agent is supposed to provide it?
- each criterion: passed or not, with a short evidence (quote or fact);
- each forbidden behaviour: violated or not, with evidence;
- scores 1-5: understanding (got the request), accuracy (correct information,
  no invention), concision (short replies fit for the phone), tone (polite,
  adapted to the caller's mood), resolution (handled the call to its end);
- "failure_node": the agent node where things went wrong, if any (exact name);
- "issues": up to 3 short sentences on what the agent should do better;
- "scenario_issue": when the call failed because of the SCENARIO, not the
  agent (the caller lacked information any real caller would have, a
  criterion asks for something the agent is not built to do, contradictory
  facts...), say it in one sentence; otherwise null.
{channel_note}
Write in {language}. Answer only with JSON:
{"goal_reached": bool, "criteria": [{"index": int, "pass": bool, "evidence": str}],
 "forbidden": [{"index": int, "violated": bool, "evidence": str}],
 "scores": {"understanding": int, "accuracy": int, "concision": int, "tone": int, "resolution": int},
 "failure_node": str|null, "summary": str, "issues": [str], "scenario_issue": str|null}"""

CHANNEL_NOTES = {
    "phone": "The transcript comes from speech recognition on a real phone "
    "call: small transcription errors are normal; do not blame the agent for "
    "words the recognition got wrong unless it should have asked again.",
    "text": "The call was played as text: there is no audio, timing or "
    "interruption to judge.",
}
SCORE_KEYS = ("understanding", "accuracy", "concision", "tone", "resolution")


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value or "").lower())


def _same(a: Any, b: Any) -> bool:
    x, y = _norm(a), _norm(b)
    return bool(x) and bool(y) and (x == y or x in y or y in x)


def call_metrics(run: dict, index: dict | None) -> dict:
    """Facts of one agent run (same digestion as the configuration analysis)."""
    from api.brand.analysis import digest_run
    from api.brand.insights import _percentile

    digest = digest_run(run, index)
    usage = run.get("usage_info") or {}
    gathered = run.get("gathered_context") or {}
    messages = digest["messages"]
    turns = [t for t in digest["turns"] if not t["greeting"]]
    greeting = next((t for t in digest["turns"] if t["greeting"]), None)
    path_ids, path = [], []
    for t in digest["transitions"]:
        if t.get("node_id") and (not path_ids or path_ids[-1] != t["node_id"]):
            path_ids.append(t["node_id"])
            path.append(t.get("node") or t["node_id"])
    if not path_ids and index:  # text runs may not log the start node
        pass
    duration = usage.get("call_duration_seconds")
    if not isinstance(duration, (int, float)):
        times = [m["start"] for m in messages if m["start"]]
        duration = (max(times) - min(times)).total_seconds() if len(times) > 1 else None
    totals = [t["total_ms"] for t in turns]
    return {
        "duration_seconds": round(duration, 1) if duration is not None else None,
        "caller_turns": sum(1 for m in messages if m["role"] == "caller"),
        "agent_turns": sum(1 for m in messages if m["role"] == "agent"),
        "interruptions": sum(
            1 for m in messages if m["role"] == "agent" and m["interrupted"]
        ),
        "latency": {
            "turns": len(totals),
            "p50_ms": _percentile(totals, 0.5),
            "p90_ms": _percentile(totals, 0.9),
            "greeting_ms": greeting["total_ms"] if greeting else None,
            "stages": {
                stage: _percentile([t["stages"][stage] for t in turns], 0.5)
                for stage in (turns[0]["stages"] if turns else {})
            },
            "values_ms": [round(v) for v in totals],
            "turn_stages": [
                {
                    "total": round(t["total_ms"]),
                    "stages": {k: round(v) for k, v in t["stages"].items()},
                }
                for t in turns
            ],
        },
        "tools": [
            {"name": t["name"], "ms": t["ms"], "failed": t["failed"]}
            for t in digest["tools"]
        ],
        "path": path,
        "path_ids": path_ids,
        "edges": [
            t["pathway"]["id"] for t in digest["transitions"] if t.get("pathway")
        ],
        "end_node": path[-1] if path else None,
        "end_status": str(gathered.get("call_status") or ""),
        "extracted_variables": gathered.get("extracted_variables") or {},
        "errors": digest["errors"],
        "models": digest["models"],
    }


def deterministic_checks(scenario: dict, metrics: dict) -> list[dict]:
    checks = []
    if scenario.get("expected_end_node"):
        expected = scenario["expected_end_node"]
        checks.append(
            {
                "kind": "end_node",
                "label": f"Ends in “{expected}”",
                "pass": _same(metrics.get("end_node"), expected)
                and _norm(metrics.get("end_node")) == _norm(expected),
                "detail": f"ended in “{metrics.get('end_node') or '?'}”",
            }
        )
    called = [t["name"] for t in metrics.get("tools") or []]
    for name in scenario.get("expected_tools") or []:
        checks.append(
            {
                "kind": "tool",
                "label": f"Calls {name}",
                "pass": any(_same(name, c) for c in called),
                "detail": ", ".join(sorted(set(called))) or "no tool called",
            }
        )
    extracted = metrics.get("extracted_variables") or {}
    for name, expected in (scenario.get("expected_variables") or {}).items():
        got = next((v for k, v in extracted.items() if _norm(k) == _norm(name)), None)
        checks.append(
            {
                "kind": "variable",
                "label": f"{name} = {expected}",
                "pass": got is not None and _same(got, expected),
                "detail": f"extracted: {got!r}" if got is not None else "not extracted",
            }
        )
    return checks


def final_verdict(
    judge: dict | None, checks: list[dict], criteria: int, error: str | None = None
) -> str:
    if error or not judge:
        return "fail"
    if any(f.get("violated") for f in judge.get("forbidden") or []):
        return "fail"
    failed = sum(1 for c in judge.get("criteria") or [] if not c.get("pass"))
    failed_checks = sum(1 for c in checks if not c["pass"])
    if not judge.get("goal_reached"):
        return "fail" if failed > criteria / 2 or not criteria else "partial"
    if failed == 0 and failed_checks == 0:
        return "pass"
    return "partial" if failed <= max(1, criteria // 2) else "fail"


def _transcript(run: dict) -> list[str]:
    from api.brand.fixes import call_excerpt

    return call_excerpt(run)["transcript"]


async def _evaluate(execution: dict, call: dict, ctx: dict) -> None:
    from api.brand.llm import chat_json

    org = ctx["organization_id"]
    runs = await brand_db.get_runs_by_ids([call["agent_run_id"]], organization_id=org)
    if not runs:
        raise ExecutionError("the agent's call was not found")
    run = runs[0]
    metrics = call_metrics(run, ctx["index"])
    scenario = call["scenario"]
    checks = deterministic_checks(scenario, metrics)
    judge, judge_error = None, None
    try:
        judge = await chat_json(
            ctx["model"],
            JUDGE_PROMPT.replace("{language}", execution["language"]).replace(
                "{channel_note}", CHANNEL_NOTES[execution["channel"]]
            ),
            {
                "scenario": {
                    "title": scenario.get("title"),
                    "goal": scenario.get("goal"),
                    "caller_behaviour": scenario.get("behaviour"),
                    "facts_given_by_caller": scenario.get("facts"),
                    "criteria": [
                        {"index": i + 1, "text": c}
                        for i, c in enumerate(scenario.get("criteria") or [])
                    ],
                    "forbidden": [
                        {"index": i + 1, "text": c}
                        for i, c in enumerate(scenario.get("forbidden") or [])
                    ],
                },
                "agent": {
                    "nodes": [
                        {
                            "name": n.get("name"),
                            "type": n.get("type"),
                            "prompt": (n.get("prompt") or "")[:800],
                        }
                        for n in ctx["brief"].get("nodes") or []
                    ],
                    "transitions": ctx["brief"].get("transitions"),
                },
                "transcript": _transcript(run)[:120],
                "extracted_variables": metrics["extracted_variables"],
                "ended": {
                    "status": metrics["end_status"],
                    "by": call.get("ended_by"),
                    "last_node": metrics["end_node"],
                },
            },
            max_tokens=2500,
            timeout=180.0,
        )
    except Exception as e:  # keep the call; only the verdict is missing
        logger.warning(f"Judge failed for test call {run['id']}: {e}")
        judge_error = str(e)
    criteria = scenario.get("criteria") or []
    by_index = {
        int(c.get("index", 0)): c
        for c in (judge or {}).get("criteria") or []
        if isinstance(c, dict)
    }
    forbidden_by = {
        int(c.get("index", 0)): c
        for c in (judge or {}).get("forbidden") or []
        if isinstance(c, dict)
    }
    scores = {
        k: max(1, min(5, int(v)))
        for k, v in ((judge or {}).get("scores") or {}).items()
        if k in SCORE_KEYS and isinstance(v, (int, float))
    }
    call.update(
        metrics=metrics,
        checks=checks,
        judge=(
            {
                "goal_reached": bool((judge or {}).get("goal_reached")),
                "criteria": [
                    {
                        "text": text,
                        "pass": bool((by_index.get(i + 1) or {}).get("pass")),
                        "evidence": str(
                            (by_index.get(i + 1) or {}).get("evidence") or ""
                        ),
                    }
                    for i, text in enumerate(criteria)
                ],
                "forbidden": [
                    {
                        "text": text,
                        "violated": bool(
                            (forbidden_by.get(i + 1) or {}).get("violated")
                        ),
                        "evidence": str(
                            (forbidden_by.get(i + 1) or {}).get("evidence") or ""
                        ),
                    }
                    for i, text in enumerate(scenario.get("forbidden") or [])
                ],
                "scores": scores,
                "failure_node": (judge or {}).get("failure_node"),
                "summary": str((judge or {}).get("summary") or ""),
                "issues": [str(i) for i in (judge or {}).get("issues") or []][:3],
                "scenario_issue": (judge or {}).get("scenario_issue") or None,
                "error": judge_error,
            }
            if judge or judge_error
            else None
        ),
    )
    call["verdict"] = (
        final_verdict(call["judge"], checks, len(criteria))
        if judge
        else None  # inconclusive: the judge did not answer
    )
    call["technical"] = call_technical(
        call, ctx.get("thresholds") or THRESHOLD_DEFAULTS, channel=execution["channel"]
    )


# --- Report -----------------------------------------------------------------------------


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def _median(values: list[float]) -> float | None:
    from api.brand.insights import _percentile

    v = _percentile([x for x in values if x is not None], 0.5)
    return round(v, 1) if v is not None else None


def _p90(values: list[float]) -> float | None:
    from api.brand.insights import _percentile

    v = _percentile([x for x in values if x is not None], 0.9)
    return round(v, 1) if v is not None else None


def aggregate(
    execution: dict, index: dict | None, thresholds: dict | None = None
) -> dict:
    calls = execution["calls"]
    judged = [c for c in calls if c.get("status") == "done" and c.get("verdict")]
    played = [c for c in calls if c.get("status") == "done"]
    verdicts = Counter(c["verdict"] for c in judged)

    by_scenario: dict[str, dict] = {}
    for c in calls:
        s = by_scenario.setdefault(
            c["scenario_id"],
            {
                "scenario_id": c["scenario_id"],
                "title": c["scenario"].get("title"),
                "levels": c["scenario"].get("levels"),
                "calls": 0,
                "pass": 0,
                "partial": 0,
                "fail": 0,
                "error": 0,
                "scores": [],
            },
        )
        s["calls"] += 1
        if c.get("status") == "error":
            s["error"] += 1
        elif c.get("verdict") in VERDICTS:
            s[c["verdict"]] += 1
        if c.get("judge") and c["judge"].get("scores"):
            s["scores"].append(
                sum(c["judge"]["scores"].values()) / len(c["judge"]["scores"])
            )
    for s in by_scenario.values():
        decided = s["pass"] + s["partial"] + s["fail"]
        s["pass_rate"] = _pct(s["pass"], decided)
        s["score"] = _pct(s["pass"] + 0.5 * s["partial"], decided)
        s["unstable"] = sum(1 for k in VERDICTS if s[k]) > 1
        s["avg_score"] = (
            round(sum(s["scores"]) / len(s["scores"]), 2) if s["scores"] else None
        )
        del s["scores"]

    by_dimension: dict[str, dict] = {}
    for key in campaigns.DIMENSIONS:
        levels: dict[int, dict] = defaultdict(
            lambda: {"calls": 0, "pass": 0, "partial": 0}
        )
        for c in judged:
            level = (c["scenario"].get("levels") or {}).get(key)
            if level is None:
                continue
            levels[int(level)]["calls"] += 1
            levels[int(level)]["pass"] += 1 if c["verdict"] == "pass" else 0
            levels[int(level)]["partial"] += 1 if c["verdict"] == "partial" else 0
        by_dimension[key] = {
            str(level): {**v, "pass_rate": _pct(v["pass"], v["calls"])}
            for level, v in sorted(levels.items())
        }
    speed_buckets: dict[str, dict] = defaultdict(lambda: {"calls": 0, "pass": 0})
    for c in judged:
        speed = c["scenario"].get("speed")
        if speed is None:
            continue
        bucket = (
            "slow (< 0.95)"
            if speed < 0.95
            else "fast (> 1.15)" if speed > 1.15 else "normal"
        )
        speed_buckets[bucket]["calls"] += 1
        speed_buckets[bucket]["pass"] += 1 if c["verdict"] == "pass" else 0
    by_dimension["speed"] = {
        k: {**v, "pass_rate": _pct(v["pass"], v["calls"])}
        for k, v in speed_buckets.items()
    }

    metrics = [c["metrics"] for c in played if c.get("metrics")]
    turn_values = [v for m in metrics for v in m["latency"]["values_ms"]]
    stage_values: dict[str, list[float]] = defaultdict(list)
    for m in metrics:
        for stage, v in (m["latency"].get("stages") or {}).items():
            if v is not None:
                stage_values[stage].append(v)
    tools: dict[str, dict] = defaultdict(lambda: {"calls": 0, "failed": 0, "ms": []})
    for m in metrics:
        for t in m["tools"]:
            tools[t["name"]]["calls"] += 1
            tools[t["name"]]["failed"] += 1 if t["failed"] else 0
            if t["ms"] is not None:
                tools[t["name"]]["ms"].append(t["ms"])

    visited = {nid for m in metrics for nid in m["path_ids"]}
    used = {eid for m in metrics for eid in m["edges"]}
    names = (index or {}).get("names") or {}
    edges = (index or {}).get("edges") or []
    coverage = {
        "nodes_total": len(names),
        "nodes_visited": len(visited & set(names)),
        "edges_total": len(edges),
        "edges_used": len(used & {e["id"] for e in edges}),
        "nodes_never_visited": [n for nid, n in names.items() if nid not in visited],
        "edges_never_used": [
            {
                "from": names.get(e["source"], e["source"]),
                "to": names.get(e["target"], e["target"]),
                "label": e["label"],
            }
            for e in edges
            if e["id"] not in used
        ],
        "node_visits": dict(
            Counter(names.get(nid, nid) for m in metrics for nid in set(m["path_ids"]))
        ),
    }
    coverage["nodes_rate"] = _pct(coverage["nodes_visited"], coverage["nodes_total"])
    coverage["edges_rate"] = _pct(coverage["edges_used"], coverage["edges_total"])

    scores: dict[str, list[int]] = defaultdict(list)
    criteria_failures: Counter = Counter()
    failure_nodes: Counter = Counter()
    checks_failed: Counter = Counter()
    for c in judged:
        judge = c.get("judge") or {}
        for k, v in (judge.get("scores") or {}).items():
            scores[k].append(v)
        for cr in judge.get("criteria") or []:
            if not cr["pass"]:
                criteria_failures[cr["text"]] += 1
        if judge.get("failure_node") and c["verdict"] != "pass":
            failure_nodes[judge["failure_node"]] += 1
        for ch in c.get("checks") or []:
            if not ch["pass"]:
                checks_failed[ch["label"]] += 1

    durations = [
        m["duration_seconds"] for m in metrics if m["duration_seconds"] is not None
    ]
    tool_calls = sum(t["calls"] for t in tools.values())
    technical = technical_report(
        calls,
        thresholds or THRESHOLD_DEFAULTS,
        channel=execution.get("channel", "phone"),
    )
    return {
        "computed_at": _now(),
        "technical": technical,
        # Mean of the judge's 1-5 scores: the answer quality, next to the
        # technical score.
        "quality_score": (
            round(
                sum(v for x in scores.values() for v in x)
                / sum(len(x) for x in scores.values()),
                2,
            )
            if any(scores.values())
            else None
        ),
        "technical_posts": {
            p["key"]: {"p50": p["p50"], "score": p["score"]} for p in technical["posts"]
        },
        "calls": len(calls),
        "played": len(played),
        "judged": len(judged),
        "errors": sum(1 for c in calls if c.get("status") == "error"),
        "cancelled": sum(1 for c in calls if c.get("status") == "cancelled"),
        "verdicts": {k: verdicts.get(k, 0) for k in VERDICTS},
        "pass_rate": _pct(verdicts.get("pass", 0), len(judged)),
        "score": _pct(
            verdicts.get("pass", 0) + 0.5 * verdicts.get("partial", 0), len(judged)
        ),
        "goal_rate": _pct(
            sum(1 for c in judged if (c.get("judge") or {}).get("goal_reached")),
            len(judged),
        ),
        "scores": {k: round(sum(v) / len(v), 2) for k, v in scores.items() if v},
        "by_scenario": sorted(
            by_scenario.values(),
            key=lambda s: (s["score"] if s["score"] is not None else 2),
        ),
        "by_dimension": by_dimension,
        "latency": {
            "turns": len(turn_values),
            "p50_ms": _median(turn_values),
            "p90_ms": _p90(turn_values),
            "greeting_p50_ms": _median(
                [
                    m["latency"]["greeting_ms"]
                    for m in metrics
                    if m["latency"]["greeting_ms"]
                ]
            ),
            "slow_turns_rate": _pct(
                sum(1 for v in turn_values if v > 2000), len(turn_values)
            ),
            "stages_p50_ms": {k: _median(v) for k, v in stage_values.items()},
        },
        "interruptions": {
            "total": sum(m["interruptions"] for m in metrics),
            "per_call": (
                round(sum(m["interruptions"] for m in metrics) / len(metrics), 2)
                if metrics
                else None
            ),
            "calls_rate": _pct(
                sum(1 for m in metrics if m["interruptions"]), len(metrics)
            ),
        },
        "tools": {
            "calls": tool_calls,
            "failure_rate": _pct(sum(t["failed"] for t in tools.values()), tool_calls),
            "by_tool": {
                name: {
                    "calls": t["calls"],
                    "failed": t["failed"],
                    "avg_ms": round(sum(t["ms"]) / len(t["ms"])) if t["ms"] else None,
                }
                for name, t in tools.items()
            },
        },
        "coverage": coverage,
        "duration": {
            "p50_seconds": _median(durations),
            "p90_seconds": _p90(durations),
            "turns_p50": _median(
                [m["caller_turns"] + m["agent_turns"] for m in metrics]
            ),
        },
        "end_status": dict(Counter(m["end_status"] or "?" for m in metrics)),
        "criteria_failures": [
            {"text": t, "count": n} for t, n in criteria_failures.most_common(10)
        ],
        "checks_failed": [
            {"label": t, "count": n} for t, n in checks_failed.most_common(10)
        ],
        "failure_nodes": dict(failure_nodes.most_common(10)),
        "scenario_issues": [
            {
                "index": c["index"],
                "scenario_id": c["scenario_id"],
                "title": c["scenario"].get("title"),
                "issue": (c.get("judge") or {}).get("scenario_issue"),
            }
            for c in judged
            if (c.get("judge") or {}).get("scenario_issue")
        ],
    }


# --- Comparison -----------------------------------------------------------------------

INDICATORS = (
    # key path, label, better ("higher" / "lower"), kind
    ("pass_rate", "Pass rate", "higher", "rate"),
    ("score", "Score (pass + ½ partial)", "higher", "rate"),
    ("goal_rate", "Goal reached", "higher", "rate"),
    ("quality_score", "Quality score (1-5)", "higher", "score"),
    ("technical.score", "Technical score (1-5)", "higher", "score"),
    ("scores.understanding", "Understanding (1-5)", "higher", "score"),
    ("scores.accuracy", "Accuracy (1-5)", "higher", "score"),
    ("scores.concision", "Concision (1-5)", "higher", "score"),
    ("scores.tone", "Tone (1-5)", "higher", "score"),
    ("scores.resolution", "Resolution (1-5)", "higher", "score"),
    ("latency.p50_ms", "Reply latency p50", "lower", "ms"),
    ("latency.p90_ms", "Reply latency p90", "lower", "ms"),
    ("latency.greeting_p50_ms", "Greeting latency p50", "lower", "ms"),
    ("technical_posts.endpointing.p50", "End-of-turn detection p50", "lower", "ms"),
    ("technical_posts.transcriber.p50", "Transcriber p50", "lower", "ms"),
    ("technical_posts.llm.p50", "LLM p50", "lower", "ms"),
    ("technical_posts.voice.p50", "Voice p50", "lower", "ms"),
    ("latency.slow_turns_rate", "Replies over 2 s", "lower", "rate"),
    ("interruptions.per_call", "Interruptions per call", "lower", "number"),
    ("tools.failure_rate", "Tool failures", "lower", "rate"),
    ("coverage.nodes_rate", "Nodes visited", "higher", "rate"),
    ("coverage.edges_rate", "Transitions used", "higher", "rate"),
    ("duration.p50_seconds", "Call duration p50", "lower", "seconds"),
    ("duration.turns_p50", "Turns per call p50", "lower", "number"),
)


def _at(report: dict, path: str) -> Any:
    value: Any = report
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


SCORE_LABELS = {
    "understanding": "Understanding",
    "accuracy": "Accuracy",
    "concision": "Concision",
    "tone": "Tone",
    "resolution": "Resolution",
}


def _headline(a: float | None, b: float | None, rows: list[dict]) -> dict:
    for row in rows:
        row["delta"] = (
            round(row["b"] - row["a"], 2)
            if isinstance(row.get("a"), (int, float))
            and isinstance(row.get("b"), (int, float))
            else None
        )
    return {
        "a": a,
        "b": b,
        "delta": round(b - a, 2) if a is not None and b is not None else None,
        "rows": rows,
    }


def _post_rows(ta: dict, tb: dict) -> list[dict]:
    """Technical posts side by side: score (1-5) and median value."""
    pa = {p["key"]: p for p in ta.get("posts") or []}
    pb = {p["key"]: p for p in tb.get("posts") or []}
    rows = []
    for key in dict.fromkeys([*pa, *pb]):
        x, y = pa.get(key) or {}, pb.get(key) or {}
        rows.append(
            {
                "key": key,
                "label": (y or x).get("label"),
                "unit": (y or x).get("unit"),
                "a": x.get("score"),
                "b": y.get("score"),
                "a_value": x.get("p50"),
                "b_value": y.get("p50"),
            }
        )
    return rows


def compare_reports(a: dict, b: dict) -> dict:
    """Indicators and scenario outcomes of execution ``b`` against ``a``."""
    ra, rb = a.get("report") or {}, b.get("report") or {}
    indicators = []
    for path, label, better, kind in INDICATORS:
        va, vb = _at(ra, path), _at(rb, path)
        delta = (
            round(vb - va, 4)
            if isinstance(va, (int, float)) and isinstance(vb, (int, float))
            else None
        )
        trend = None
        if delta:
            trend = "better" if (delta > 0) == (better == "higher") else "worse"
        indicators.append(
            {
                "key": path,
                "label": label,
                "kind": kind,
                "better": better,
                "a": va,
                "b": vb,
                "delta": delta,
                "trend": trend or ("same" if delta == 0 else None),
            }
        )
    sa = {s["scenario_id"]: s for s in ra.get("by_scenario") or []}
    sb = {s["scenario_id"]: s for s in rb.get("by_scenario") or []}
    scenarios = []
    for sid in list(dict.fromkeys([*sa, *sb])):
        x, y = sa.get(sid), sb.get(sid)
        change = "new" if x is None else "removed" if y is None else None
        if change is None:
            if x["score"] is None or y["score"] is None:
                change = "unknown"
            elif y["score"] > x["score"] + 1e-9:
                change = "improved"
            elif y["score"] < x["score"] - 1e-9:
                change = "regressed"
            else:
                change = "same"
        scenarios.append(
            {
                "scenario_id": sid,
                "title": (y or x)["title"],
                "a": (
                    {
                        k: x.get(k)
                        for k in ("calls", "pass", "partial", "fail", "error", "score")
                    }
                    if x
                    else None
                ),
                "b": (
                    {
                        k: y.get(k)
                        for k in ("calls", "pass", "partial", "fail", "error", "score")
                    }
                    if y
                    else None
                ),
                "change": change,
            }
        )
    headline = {
        "quality": _headline(
            ra.get("quality_score"),
            rb.get("quality_score"),
            [
                {
                    "key": k,
                    "label": SCORE_LABELS[k],
                    "a": (ra.get("scores") or {}).get(k),
                    "b": (rb.get("scores") or {}).get(k),
                }
                for k in SCORE_KEYS
            ],
        ),
        "technical": _headline(
            (ra.get("technical") or {}).get("score"),
            (rb.get("technical") or {}).get("score"),
            _post_rows(ra.get("technical") or {}, rb.get("technical") or {}),
        ),
    }
    order = {
        "regressed": 0,
        "improved": 1,
        "unknown": 2,
        "new": 3,
        "removed": 4,
        "same": 5,
    }
    scenarios.sort(key=lambda s: order[s["change"]])
    ca, cb = ra.get("coverage") or {}, rb.get("coverage") or {}
    never_a, never_b = set(ca.get("nodes_never_visited") or []), set(
        cb.get("nodes_never_visited") or []
    )
    return {
        "headline": headline,
        "indicators": indicators,
        "scenarios": scenarios,
        "changes": dict(Counter(s["change"] for s in scenarios)),
        "coverage": {
            "nodes_gained": sorted(never_a - never_b),
            "nodes_lost": sorted(never_b - never_a),
        },
    }


async def compare(organization_id: int, a_id: str, b_id: str) -> dict:
    from api.brand.version_diff import diff_versions
    from api.brand.versions import _snapshot

    a, b = await get(organization_id, a_id), await get(organization_id, b_id)
    if a is None or b is None:
        raise LookupError("execution not found")
    result = compare_reports(a, b)
    brief = lambda e: {  # noqa: E731
        k: e.get(k)
        for k in (
            "id",
            "campaign_id",
            "campaign_name",
            "workflow_id",
            "workflow_name",
            "definition_id",
            "version_number",
            "version_status",
            "channel",
            "passes",
            "personas",
            "created_at",
            "finished_at",
            "status",
        )
    }
    result["a"], result["b"] = brief(a), brief(b)
    result["version_diff"] = None
    if (
        a["workflow_id"] == b["workflow_id"]
        and a["definition_id"] != b["definition_id"]
    ):

        async def version(e: dict) -> dict | None:
            v = await brand_db.get_workflow_version(
                e["workflow_id"], e["definition_id"]
            )
            return _snapshot(v) if v is not None else e.get("definition_snapshot")

        va, vb = await version(a), await version(b)
        if va is not None and vb is not None:
            result["version_diff"] = diff_versions(va, vb)
        else:
            result["version_unavailable"] = True
    # Only executions made since the snapshot existed can be compared.
    if "engine_snapshot" in a and "engine_snapshot" in b:
        result["engine_changes"] = engine_changes(
            a.get("engine_snapshot"), b.get("engine_snapshot")
        )
    return result


# --- Fix from a failed test call -----------------------------------------------------------


def finding_from_call(execution: dict, call: dict) -> dict:
    """An analysis-like finding for the automatic fixes (fixes.create)."""
    judge = call.get("judge") or {}
    failed = [c["text"] for c in judge.get("criteria") or [] if not c["pass"]]
    failed += [
        f"Forbidden: {f['text']}" for f in judge.get("forbidden") or [] if f["violated"]
    ]
    failed += [c["label"] for c in call.get("checks") or [] if not c["pass"]]
    scenario = call["scenario"]
    return {
        "id": f"test-{execution['id']}-{call['index']}",
        "rule": None,
        "severity": "high" if call.get("verdict") == "fail" else "medium",
        "category": "test",
        "title": f"Test scenario failed: {scenario.get('title')}",
        "detail": " ".join(
            filter(
                None,
                [
                    judge.get("summary"),
                    ("Failed: " + "; ".join(failed) + ".") if failed else None,
                    (
                        ("To improve: " + " ".join(judge.get("issues") or []))
                        if judge.get("issues")
                        else None
                    ),
                ],
            )
        ),
        "agent": execution["workflow_name"],
        "node": judge.get("failure_node"),
        "metrics": {
            "verdict": call.get("verdict"),
            "scenario_goal": scenario.get("goal"),
        },
        "recommendation": " ".join(judge.get("issues") or []) or None,
        "calls": [call["agent_run_id"]] if call.get("agent_run_id") else [],
    }

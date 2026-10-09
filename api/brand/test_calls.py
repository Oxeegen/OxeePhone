"""Hooks of the test campaigns in the call pipeline (gated upstream edits).

Caller side (the tester agent, outbound): ``tester_configs`` gives each call
its own voice, voice speed and speaking plan (impatience), and the tester
listens first instead of greeting (``listens_first``).

Agent side (inbound): a test call carries a one-time token in its CallerID
name (``"OXT<token>" <customer number>``). ``claim_inbound`` finds the pending
test call it was placed for, so the call runs the agent version under test
(published, draft or older), under a run name kept out of the production
statistics. A real caller cannot run a draft: the token is random, single-use
and expires.

Tools of the agent under test (``tool_override``): simulated by the analysis
model from the scenario's hints, executed for real, or executed for real with
an ``X-Oxee-Test: 1`` header (HTTP tools), as chosen per campaign.
"""

from __future__ import annotations

import asyncio
import copy
import re
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from loguru import logger

from api.brand.db import TEST_RUN_PREFIX

CALL_PREFIX = "OXEE_TESTCALL:"
CALLER_NAME_TAG = "OXT"
TOKEN = re.compile(CALLER_NAME_TAG + r"([0-9a-f]{12})")
CLAIM_WINDOW = timedelta(minutes=10)
TEST_HEADER = "X-Oxee-Test"
SIMULATED_TOOL_TIMEOUT = 4.0

# --- Caller side ------------------------------------------------------------------

# Impatience level → when the tester takes the floor (seconds): wait, after a
# sentence, after an unfinished phrase, after a number. Low values make the
# tester answer in the agent's short pauses, i.e. interrupt it.
IMPATIENCE_PLANS = {
    1: (0.8, 0.6, 1.8, 1.0),
    2: (0.5, 0.4, 1.4, 0.8),
    3: (0.3, 0.2, 1.0, 0.6),
    4: (0.1, 0.1, 0.6, 0.4),
    5: (0.0, 0.05, 0.3, 0.2),
}


def impatience_plan(level: int) -> dict:
    wait, punct, no_punct, number = IMPATIENCE_PLANS.get(
        int(level or 1), IMPATIENCE_PLANS[1]
    )
    return {
        "start": {
            "wait_seconds": wait,
            "smart_endpointing": "off",
            "on_punctuation_seconds": punct,
            "on_no_punctuation_seconds": no_punct,
            "on_number_seconds": number,
        },
        "stop": {"num_words": 2, "voice_seconds": 0.2, "backoff_seconds": 0.5},
    }


def tester_of(context: dict | None) -> dict | None:
    tester = (context or {}).get("oxee_tester")
    return tester if isinstance(tester, dict) else None


def tester_configs(run_configs: dict, context: dict | None) -> dict:
    """The tester agent's configuration for this call (others: unchanged)."""
    from api.brand.fixes import _speaking_plan_config

    tester = tester_of(context)
    if tester is None:
        return run_configs
    from api.brand.agent_tuning import VOICE_KEY

    configs = copy.deepcopy(run_configs or {})
    voice = dict(configs.get(VOICE_KEY) or {})
    if tester.get("voice"):
        voice["voice"] = str(tester["voice"])
    if tester.get("speed"):
        voice["speed"] = float(tester["speed"])
    if voice:
        configs[VOICE_KEY] = voice
    configs.update(_speaking_plan_config(impatience_plan(tester.get("impatience", 1))))
    configs["max_call_duration"] = int(tester.get("max_duration") or 300)
    configs["max_user_idle_timeout"] = 15
    return configs


def listens_first(context: dict | None) -> bool:
    """The tester waits for the agent's greeting instead of opening."""
    return tester_of(context) is not None


# On a phone call the agent answers and greets at once, while the tester's
# pipeline is still starting (answer, ARI external media, websocket): the
# tester can miss the greeting, and both sides would then wait for each other.
TESTER_OPENING_SECS = 6.0
OPENING_CUE = (
    "(The call is connected but you heard no greeting, or only part of it. "
    "Speak first: greet and say why you are calling.)"
)
_openings: set = set()


def _heard_something(engine: Any) -> bool:
    context = getattr(engine, "context", None)
    try:
        messages = context.get_messages() if context is not None else []
    except Exception:
        return False
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role == "user":
            return True
    return False


def schedule_tester_opening(engine: Any, node_id: str) -> None:
    """The tester opens the conversation itself when it has neither spoken
    nor heard the agent within TESTER_OPENING_SECS (natural path otherwise:
    it answers the greeting it heard)."""

    async def watch() -> None:
        await asyncio.sleep(TESTER_OPENING_SECS)
        started = getattr(engine, "_speech_playback_started", None)
        if (started is not None and started.is_set()) or _heard_something(engine):
            return
        logger.info("Test caller heard no greeting: it opens the conversation")
        try:
            # Chat templates such as Qwen's refuse a conversation without a
            # user turn ("No user query found in messages").
            engine.context.add_message({"role": "user", "content": OPENING_CUE})
            await engine.queue_node_opening(
                node_id=node_id, previous_node_id=None, generate_if_no_greeting=True
            )
        except Exception as e:  # the call may be over already
            logger.warning(f"Test caller opening failed: {e}")

    task = asyncio.create_task(watch())
    _openings.add(task)
    task.add_done_callback(_openings.discard)


# --- Agent side -------------------------------------------------------------------


def new_token() -> str:
    return secrets.token_hex(6)


def caller_id(token: str, number: str) -> str:
    return f'"{CALLER_NAME_TAG}{token}" <{number}>'


async def register_call(organization_id: int, token: str, record: dict) -> None:
    from api.db import db_client

    await db_client.upsert_configuration(
        organization_id,
        CALL_PREFIX + token,
        {**record, "token": token, "created_at": datetime.now(UTC).isoformat()},
    )


async def forget_call(organization_id: int, token: str) -> None:
    from api.brand.db import delete_configuration

    await delete_configuration(organization_id, CALL_PREFIX + token)


async def claim_inbound(
    organization_id: int,
    caller_name: str | None,
    caller_number: str | None = None,
    called_number: str | None = None,
) -> dict | None:
    """The pending test call an inbound call belongs to, claimed once.

    Returns ``{workflow_id, definition_id, run_name, context}`` or None for an
    ordinary call.
    """
    from api.db import db_client

    match = TOKEN.search(caller_name or "")
    try:
        if match:
            token = match.group(1)
            row = await db_client.get_configuration(
                organization_id, CALL_PREFIX + token
            )
            record = dict(row.value) if row and row.value else None
        else:
            # The PBX or a trunk may drop the CallerID name: when the test
            # settings say so, the oldest pending test call is taken.
            record = await _oldest_pending_call(organization_id)
            if record is None:
                return None
            token = record["token"]
        if not record or record.get("claimed_at"):
            return None
        created = datetime.fromisoformat(record["created_at"])
        if datetime.now(UTC) - created > CLAIM_WINDOW:
            return None
        record["claimed_at"] = datetime.now(UTC).isoformat()
        record["called_number"] = called_number
        await db_client.upsert_configuration(
            organization_id, CALL_PREFIX + token, record
        )
    except Exception as e:  # never break a real inbound call
        logger.warning(f"Test call lookup failed: {e}")
        return None
    logger.info(
        f"Inbound test call {token}: agent {record['workflow_id']} "
        f"version {record['definition_id']}"
    )
    return {
        "workflow_id": int(record["workflow_id"]),
        "definition_id": int(record["definition_id"]),
        "run_name": record["agent_run_name"],
        "context": {"oxee_test": record["test"]},
    }


ARRIVAL_WINDOW = timedelta(seconds=45)


async def _oldest_pending_call(organization_id: int) -> dict | None:
    """With pairing "arrival order": the oldest unclaimed test call placed in
    the last ARRIVAL_WINDOW (executions then place one call at a time)."""
    from api.brand import test_campaigns
    from api.brand.db import list_configurations_by_prefix

    settings = await test_campaigns.get_settings(organization_id)
    if settings.get("pairing") != "arrival_order":
        return None
    now = datetime.now(UTC)
    pending = [
        r
        for r in await list_configurations_by_prefix(
            organization_id, CALL_PREFIX, limit=50
        )
        if not r.get("claimed_at")
        and now - datetime.fromisoformat(r["created_at"]) <= ARRIVAL_WINDOW
    ]
    return min(pending, key=lambda r: r["created_at"]) if pending else None


def agent_run_name(execution_id: str, call_index: int) -> str:
    return f"{TEST_RUN_PREFIX}{execution_id}-{call_index}-agent"


def caller_run_name(execution_id: str, call_index: int) -> str:
    return f"{TEST_RUN_PREFIX}{execution_id}-{call_index}-caller"


# --- Tools of the agent under test --------------------------------------------------

SIMULATE_TOOL_PROMPT = """You play the backend of a tool called by a phone
voice agent during a TEST call. Answer with the JSON result the tool would
return for these arguments, realistic and consistent with the scenario hints
(when the hints say something is unavailable, not found or fails, answer so).
If the tool hands the call over (transfers or forwards the caller to a person,
the switchboard, a department or another number), the transfer succeeds: add
"oxee_transfer": true to the result.
Keep it short. Answer only with JSON."""


def test_of(context: dict | None) -> dict | None:
    test = (context or {}).get("oxee_test")
    return test if isinstance(test, dict) else None


async def _call_model(organization_id: int) -> dict | None:
    """The organization's call LLM (fast enough to answer within a tool call)."""
    from api.services.configuration.ai_model_configuration import (
        get_organization_ai_model_configuration_v2,
    )

    try:
        stored = await get_organization_ai_model_configuration_v2(organization_id)
        pipeline = getattr(getattr(stored, "byok", None), "pipeline", None)
        llm = getattr(pipeline, "llm", None) if pipeline else None
        if llm is None or not getattr(llm, "base_url", None):
            return None
        keys = llm.get_all_api_keys() if hasattr(llm, "get_all_api_keys") else []
        return {
            "base_url": llm.base_url,
            "api_key": keys[0] if keys else None,
            "model": llm.model,
        }
    except Exception:
        return None


async def _simulate_tool(
    organization_id: int | None,
    test: dict,
    function_name: str,
    arguments: dict,
    tool: Any,
) -> dict:
    from api.brand.analysis import resolve_analysis_model
    from api.brand.llm import chat_json

    fallback = {
        "status": "success",
        "note": "Test call: this tool was simulated.",
    }
    try:
        model = (
            (await _call_model(organization_id))
            or (await resolve_analysis_model(organization_id))
            if organization_id
            else None
        )
        if not model:
            return fallback
        definition = getattr(tool, "definition", None) or {}
        # Pipecat cancels a tool call after 5 s: answer before it does.
        return await asyncio.wait_for(
            chat_json(
                model,
                SIMULATE_TOOL_PROMPT,
                {
                    "tool": function_name,
                    "description": getattr(tool, "description", None),
                    "parameters": (
                        (definition.get("config") or {}).get("parameters")
                        if isinstance(definition, dict)
                        else None
                    ),
                    "arguments": arguments or {},
                    "scenario": test.get("scenario"),
                    "scenario_hints": test.get("tool_hints"),
                },
                max_tokens=300,
                temperature=0.3,
                timeout=SIMULATED_TOOL_TIMEOUT,
            ),
            SIMULATED_TOOL_TIMEOUT,
        )
    except Exception as e:
        logger.warning(f"Simulated tool {function_name} failed: {e!r}")
        return fallback


def skip_test_call_effects(context: dict | None) -> bool:
    """Post-call webhooks and integrations stay off for a test call unless its
    tools are real."""
    test = test_of(context)
    return test is not None and test.get("tools_mode", "simulated") == "simulated"


def _with_test_header(tool: Any) -> Any:
    columns = getattr(getattr(tool, "__table__", None), "columns", None)
    if columns is None:
        return tool
    clone = SimpleNamespace(**{c.name: getattr(tool, c.name, None) for c in columns})
    definition = copy.deepcopy(clone.definition or {})
    config = definition.setdefault("config", {})
    config["headers"] = {**(config.get("headers") or {}), TEST_HEADER: "1"}
    clone.definition = definition
    return clone


PRE_CALL_PROMPT = """You play the system (CRM, ERP, booking software...) that
answers the pre-call lookup made before a phone voice agent takes a TEST call.
Return the values this system would hold about the caller for the listed
variables (identity, customer account, history, preferences...), realistic and
consistent with the caller and the scenario hints; when the hints say the
caller is unknown or the lookup fails, return an empty object. Do not reveal
why the caller is calling unless such a system would know it. Use only the
listed variable names; leave out those such a system would not know.
Answer only with JSON: {"initial_context": {"<variable>": <value>}}"""
PRE_CALL_TIMEOUT = 8.0


def template_variables(workflow_json: dict | None, known: dict | None = None) -> list[str]:
    """Variables the agent's texts use ({{name}}), minus the built-in ones and
    those already in the call context."""
    import json
    import re

    from api.utils.template_renderer import TEMPLATE_VAR_PATTERN, is_builtin_variable

    text = json.dumps((workflow_json or {}).get("nodes") or [], ensure_ascii=False)
    names = []
    for match in re.finditer(TEMPLATE_VAR_PATTERN, text):
        name = match.group(1).strip().split(".")[0]
        if (
            name
            and name not in names
            and not is_builtin_variable(name)
            and name not in (known or {})
            and not name.startswith(("oxee_", "gathered_context"))
        ):
            names.append(name)
    return names


async def pre_call_override(
    context: dict | None, workflow_json: dict | None, organization_id: int | None
) -> dict | None:
    """Pre-call fetch of a test call whose tools are simulated: the lookup is
    answered by a model playing the system; None outside such a call."""
    from api.brand.analysis import resolve_analysis_model
    from api.brand.llm import chat_json

    test = test_of(context)
    if test is None or (test.get("tools_mode") or "simulated") != "simulated":
        return None
    variables = template_variables(workflow_json, context)
    if not variables or not organization_id:
        return {}
    try:
        model = (await _call_model(organization_id)) or (
            await resolve_analysis_model(organization_id)
        )
        if not model:
            return {}
        result = await asyncio.wait_for(
            chat_json(
                model,
                PRE_CALL_PROMPT,
                {
                    "variables": variables,
                    "caller": {
                        "number": (context or {}).get("caller_number"),
                        **(test.get("caller") or {}),
                    },
                    "scenario": test.get("scenario"),
                    "scenario_hints": test.get("tool_hints"),
                },
                max_tokens=500,
                temperature=0.3,
                timeout=PRE_CALL_TIMEOUT,
            ),
            PRE_CALL_TIMEOUT + 1,
        )
    except Exception as e:
        logger.warning(f"Simulated pre-call fetch failed: {e!r}")
        return {}
    values = result.get("initial_context") if isinstance(result, dict) else None
    if not isinstance(values, dict):
        values = result if isinstance(result, dict) else {}
    kept = {k: v for k, v in values.items() if k in variables and v not in (None, "")}
    logger.info(f"Simulated pre-call fetch for a test call: {sorted(kept)}")
    return kept


def test_direction(context: dict | None) -> str | None:
    """Direction of a text test call: it plays an inbound call."""
    return "inbound" if test_of(context) is not None else None


async def pre_call_or(real: Any, context: dict | None, workflow_json: dict | None, organization_id: int | None) -> dict:
    """The simulated lookup of a test call, else the real fetch (awaited only
    when needed)."""
    simulated = await pre_call_override(context, workflow_json, organization_id)
    if simulated is not None:
        real.close()  # never awaited
        return simulated
    return await real


TRANSFER_CONTEXT_KEY = "oxee_test_transfer"


def simulated_transfer(engine: Any, tool: Any, arguments: dict | None) -> dict | None:
    """A transfer tool called during a test call: nobody is dialled and the
    transfer succeeds (the destination "answers"), unless the campaign runs
    the agent's tools for real. Recorded in the call's context for the judge.
    """
    test = test_of(getattr(engine, "_call_context_vars", None))
    if test is None or (test.get("tools_mode") or "simulated") == "real":
        return None
    _record_transfer(engine, tool, arguments)
    return {
        "action": "destination_answered",
        "status": "success",
        "conference_id": "oxee-test-simulated",
        "simulated": True,
    }


def _record_transfer(engine: Any, tool: Any, arguments: dict | None) -> None:
    config = (getattr(tool, "definition", None) or {}).get("config") or {}
    engine.record_context(
        {
            TRANSFER_CONTEXT_KEY: {
                "tool": getattr(tool, "name", None),
                "destination": config.get("destination") or config.get("url") or None,
                "agent": config.get("workflow_id"),
                "arguments": arguments or {},
            }
        }
    )


def tool_timeout(engine: Any, timeout_secs: float | None) -> float | None:
    """Deadline of a tool in a test call whose tools are simulated: long
    enough for the simulation to answer (a tool's own deadline can be shorter
    than the model needs)."""
    test = test_of(getattr(engine, "_call_context_vars", None))
    if test is None or (test.get("tools_mode") or "simulated") != "simulated":
        return timeout_secs
    return max(timeout_secs or 0.0, SIMULATED_TOOL_TIMEOUT + 2.0)


def transfer_by_tool(engine: Any, tool: Any, arguments: dict | None, result: Any) -> bool:
    """A simulated HTTP tool that transferred the call (the simulator flagged
    it): the call is over for the agent, as when the PBX takes it away."""
    if not isinstance(result, dict) or not result.pop("oxee_transfer", False):
        return False
    if test_of(getattr(engine, "_call_context_vars", None)) is None:
        return False
    _record_transfer(engine, tool, arguments)
    return True


async def tool_override(
    engine: Any,
    function_name: str,
    arguments: dict | None,
    *,
    tool: Any = None,
    organization_id: int | None = None,
) -> Any | None:
    """Result to use instead of the normal tool execution, or None."""
    from api.brand.simulation import tool_override as replay_override

    replayed = replay_override(function_name, arguments)  # fix simulations
    if replayed is not None:
        return replayed
    test = test_of(getattr(engine, "_call_context_vars", None))
    if test is None:
        return None
    mode = test.get("tools_mode") or "simulated"
    if mode == "simulated":
        return await _simulate_tool(
            organization_id, test, function_name, arguments or {}, tool
        )
    if mode == "real_with_header" and tool is not None:
        from api.services.workflow.tools.custom_tool import execute_http_tool

        return await execute_http_tool(
            tool=_with_test_header(tool),
            arguments=arguments or {},
            call_context_vars=engine._call_context_vars,
            gathered_context_vars=engine._gathered_context,
            organization_id=organization_id,
        )
    return None

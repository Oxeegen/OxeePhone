"""Agent versions: who changed what, how, and going back.

Upstream keeps every version of an agent (draft → published → archived) with
its graph, configuration and variables, but not who made it nor how. This
module keeps that as version metadata, stored as organization configurations
``OXEE_VERSION_META:<workflow_id>:<definition_id>`` (no schema migration):

    origin          editor | api | mcp | restore | fix  (how the version was born)
    created_by      {id, email} of the first author
    restored_from   version number, for restores
    note            free text (restores, automatic fixes)
    edits           [{at, by, channel}] (last 20 saves of a draft)
    published_by / published_at
    ai_summaries    {"<base_definition_id>": {text, model, at}}

The request channel (browser, API key, MCP) comes from ``ChannelMiddleware``.
"""

from __future__ import annotations

import contextvars
import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.brand import db as brand_db
from api.brand.version_diff import diff_versions
from api.db import db_client
from api.services.configuration.masking import (
    mask_workflow_configurations,
    mask_workflow_definition,
)

META_PREFIX = "OXEE_VERSION_META:"
MAX_EDITS = 20

# --- Request channel --------------------------------------------------------

_channel: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "oxee_request_channel", default={"channel": "internal"}
)


class ChannelMiddleware:
    """Tags each request with how it reached the API (pure ASGI, so the value
    is visible to the endpoint)."""

    def __init__(self, app, api_prefix: str = "/api/v1"):
        self.app = app
        self.mcp_path = f"{api_prefix}/mcp"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode().lower(): v.decode() for k, v in scope.get("headers") or []
            }
            key = headers.get("x-api-key")
            if not key and scope.get("path", "").startswith(self.mcp_path):
                auth = headers.get("authorization", "")
                key = (
                    auth.split(" ", 1)[1].strip()
                    if auth.lower().startswith("bearer ")
                    else None
                )
            if scope.get("path", "").startswith(self.mcp_path):
                info = {"channel": "mcp"}
            elif key:
                info = {"channel": "api"}
            else:
                info = {"channel": "editor"}
            if key:
                info["api_key_prefix"] = key[:8]
            token = _channel.set(info)
            try:
                await self.app(scope, receive, send)
            finally:
                _channel.reset(token)
        else:
            await self.app(scope, receive, send)


def current_channel() -> dict:
    return dict(_channel.get())


# --- Metadata ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(workflow_id: int, definition_id: int) -> str:
    return f"{META_PREFIX}{workflow_id}:{definition_id}"


def _who(user: Any) -> dict | None:
    if user is None:
        return None
    return {"id": getattr(user, "id", None), "email": getattr(user, "email", None)}


async def get_meta(organization_id: int, workflow_id: int, definition_id: int) -> dict:
    row = await db_client.get_configuration(
        organization_id, _key(workflow_id, definition_id)
    )
    return dict(row.value) if row and row.value else {}


async def _save_meta(
    organization_id: int, workflow_id: int, definition_id: int, meta: dict
) -> None:
    meta.update({"workflow_id": workflow_id, "definition_id": definition_id})
    await db_client.upsert_configuration(
        organization_id, _key(workflow_id, definition_id), meta
    )


async def all_meta(organization_id: int, workflow_id: int) -> dict[int, dict]:
    values = await brand_db.list_configurations_by_prefix(
        organization_id, f"{META_PREFIX}{workflow_id}:", limit=1000
    )
    return {
        int(v["definition_id"]): v for v in values if v.get("definition_id") is not None
    }


async def record_edit(
    definition: Any,
    user: Any,
    *,
    organization_id: int,
    origin: str | None = None,
    note: str | None = None,
    restored_from: int | None = None,
    only_if_new: bool = False,
) -> None:
    """Called whenever a draft is created or saved. Never raises."""
    try:
        if definition is None:
            return
        channel = current_channel()
        meta = await get_meta(organization_id, definition.workflow_id, definition.id)
        if only_if_new and meta.get("origin"):
            return
        if not meta.get("origin"):
            meta["origin"] = origin or channel.get("channel", "editor")
            meta["created_by"] = _who(user)
            meta["created_at"] = _now()
            if channel.get("api_key_prefix"):
                meta["api_key_prefix"] = channel["api_key_prefix"]
        if note:
            meta["note"] = note
        if restored_from is not None:
            meta["restored_from"] = restored_from
        edits = list(meta.get("edits") or [])
        edits.append(
            {"at": _now(), "by": _who(user), "channel": channel.get("channel")}
        )
        meta["edits"] = edits[-MAX_EDITS:]
        await _save_meta(organization_id, definition.workflow_id, definition.id, meta)
    except Exception as e:  # metadata must never break a save
        logger.warning(f"Could not record the version edit: {e}")


async def record_published(definition: Any, user: Any, *, organization_id: int) -> None:
    try:
        meta = await get_meta(organization_id, definition.workflow_id, definition.id)
        meta["published_by"] = _who(user)
        meta["published_at"] = _now()
        meta["published_via"] = current_channel().get("channel")
        await _save_meta(organization_id, definition.workflow_id, definition.id, meta)
    except Exception as e:
        logger.warning(f"Could not record the publication: {e}")


# --- Listing and diff -------------------------------------------------------


def _with_defaults(configurations: dict | None) -> dict:
    """Explicit values for the keys a version left at their default, so a diff
    says "10 → 8" rather than "— → 8"."""
    from api.schemas.workflow_configurations import WorkflowConfigurationDefaults

    try:
        full = WorkflowConfigurationDefaults.model_validate(
            configurations or {}
        ).model_dump(mode="json")
    except Exception:
        full = dict(configurations or {})
    if "speaking_plan" not in full:
        full["speaking_plan"] = _speaking_plan_from_turn_settings(full)
    # Mirrors of the speaking plan (kept in line by the settings page).
    for key in ("turn_start_strategy", "turn_start_min_words", "turn_stop_strategy"):
        full.pop(key, None)
    return full


def _speaking_plan_from_turn_settings(configurations: dict) -> dict:
    """The speaking plan equivalent to upstream's turn settings (what the
    settings page shows for an agent saved before the speaking plans)."""
    from api.brand.speaking_plan import SpeakingPlan

    plan = SpeakingPlan().model_dump()
    if configurations.get("turn_stop_strategy") == "turn_analyzer":
        plan["start"]["smart_endpointing"] = "smart_turn"
    if configurations.get("turn_start_strategy") == "min_words":
        plan["stop"]["num_words"] = int(configurations.get("turn_start_min_words") or 3)
    return plan


def _snapshot(version: Any) -> dict:
    return {
        "workflow_json": mask_workflow_definition(version.workflow_json) or {},
        "workflow_configurations": mask_workflow_configurations(
            _with_defaults(version.workflow_configurations)
        )
        or {},
        "template_context_variables": version.template_context_variables or {},
    }


def _header(version: Any, meta: dict | None, calls: int | None = None) -> dict:
    meta = meta or {}
    edits = meta.get("edits") or []
    return {
        "id": version.id,
        "version_number": version.version_number,
        "status": version.status,
        "created_at": version.created_at,
        "published_at": version.published_at,
        "origin": meta.get("origin"),
        "created_by": meta.get("created_by"),
        "last_edited_at": edits[-1]["at"] if edits else None,
        "last_edited_by": edits[-1].get("by") if edits else None,
        "edit_count": len(edits),
        "published_by": meta.get("published_by"),
        "restored_from": meta.get("restored_from"),
        "note": meta.get("note"),
        "api_key_prefix": meta.get("api_key_prefix"),
        "calls": calls,
    }


async def list_versions(
    workflow_id: int, *, organization_id: int, limit: int = 30, offset: int = 0
) -> dict:
    # One extra row: the version before the page's last, for its diff.
    rows = [
        v
        for v in await db_client.get_workflow_versions(
            workflow_id, limit=limit + 1, offset=offset
        )
        if v.version_number is not None
    ]
    metas = await all_meta(organization_id, workflow_id)
    calls = await brand_db.count_runs_by_definition(
        workflow_id, organization_id=organization_id
    )
    items = []
    for i, v in enumerate(rows[:limit]):
        previous = rows[i + 1] if i + 1 < len(rows) else None
        if previous is None and v.version_number > 1:
            previous = await brand_db.get_previous_version(
                workflow_id, v.version_number
            )
        diff = diff_versions(_snapshot(previous) if previous else None, _snapshot(v))
        item = _header(v, metas.get(v.id), calls.get(v.id, 0))
        item["base_version_number"] = previous.version_number if previous else None
        item["counts"] = diff["counts"]
        item["bullets"] = diff["bullets"][:6]
        item["bullet_count"] = len(diff["bullets"])
        summaries = (metas.get(v.id) or {}).get("ai_summaries") or {}
        if previous and str(previous.id) in summaries:
            item["ai_summary"] = summaries[str(previous.id)]
        items.append(item)
    return {"items": items, "has_more": len(rows) > limit}


async def version_diff(
    workflow_id: int,
    definition_id: int,
    *,
    organization_id: int,
    base_id: int | None = None,
) -> dict | None:
    target = await brand_db.get_workflow_version(workflow_id, definition_id)
    if target is None:
        return None
    if base_id is not None:
        base = await brand_db.get_workflow_version(workflow_id, base_id)
        if base is None:
            return None
    else:
        base = await brand_db.get_previous_version(workflow_id, target.version_number)
    metas = await all_meta(organization_id, workflow_id)
    diff = diff_versions(_snapshot(base) if base else None, _snapshot(target))
    summaries = (metas.get(target.id) or {}).get("ai_summaries") or {}
    return {
        "target": _header(target, metas.get(target.id)),
        "base": _header(base, metas.get(base.id)) if base else None,
        **diff,
        "ai_summary": summaries.get(str(base.id)) if base else None,
    }


# --- AI summary ---------------------------------------------------------------

SUMMARY_PROMPT = """You summarise the changes between two versions of a voice agent
(a phone assistant built as a graph of conversation nodes linked by transitions,
plus its settings) for the people who operate it.

You receive the structured list of changes (node prompts with word-level diffs,
transition labels / conditions, settings such as the speaking plan). Write in
{language}:
- "headline": one sentence, what this version changes overall and why it
  probably matters for callers;
- "points": 2 to 6 short bullet strings, the concrete changes in plain words
  (quote node and transition names, give before → after for settings); do not
  paste whole prompts;
- "risks": 0 to 3 short bullet strings, possible side effects worth checking
  in the next calls (routing, tone, latency…). Empty list when none.

Answer with a JSON object {"headline": str, "points": [str], "risks": [str]} and
nothing else."""


def _compact_changes(diff: dict, max_chars: int = 24000) -> list[dict]:
    """The diff without huge unchanged text, for the model."""
    out = []
    for c in diff["changes"]:
        fields = []
        for f in c["fields"]:
            if "text_diff" in f:
                parts = []
                for seg in f["text_diff"]:
                    text = seg["text"]
                    if seg["op"] == "equal" and len(text) > 160:
                        text = text[:70] + " … " + text[-70:]
                    parts.append(
                        {"=": text}
                        if seg["op"] == "equal"
                        else {"+" if seg["op"] == "insert" else "-": text}
                    )
                fields.append({"field": f["label"], "diff": parts})
            else:
                fields.append(
                    {"field": f["label"], "before": f["before"], "after": f["after"]}
                )
        out.append(
            {
                "scope": c["scope"],
                "kind": c["kind"],
                "title": c["title"],
                "fields": fields,
            }
        )
    text = json.dumps(out, ensure_ascii=False, default=str)
    while len(text) > max_chars and out:
        out.pop()
        text = json.dumps(out, ensure_ascii=False, default=str)
    return out


async def summarize(
    workflow_id: int,
    definition_id: int,
    *,
    organization_id: int,
    base_id: int | None = None,
    language: str = "English",
) -> dict:
    from api.brand.analysis import resolve_analysis_model
    from api.brand.llm import chat_json

    diff = await version_diff(
        workflow_id, definition_id, organization_id=organization_id, base_id=base_id
    )
    if diff is None:
        raise LookupError("version not found")
    if diff["base"] is None:
        raise ValueError("the first version has nothing to compare with")
    if not diff["changes"]:
        summary = {
            "headline": "No functional change"
            + (" (layout only)" if diff["bullets"] else ""),
            "points": [],
            "risks": [],
            "model": None,
            "at": _now(),
        }
    else:
        model = await resolve_analysis_model(organization_id)
        if not model:
            raise ValueError("no analysis model configured (Models › Analysis)")
        result = await chat_json(
            model,
            SUMMARY_PROMPT.replace("{language}", language),
            {
                "agent_version": diff["target"]["version_number"],
                "compared_with": diff["base"]["version_number"],
                "changes": _compact_changes(diff),
            },
            max_tokens=1500,
        )
        summary = {
            "headline": str(result.get("headline") or ""),
            "points": [str(p) for p in result.get("points") or []][:8],
            "risks": [str(p) for p in result.get("risks") or []][:5],
            "model": model["model"],
            "at": _now(),
            "language": language,
        }
    meta = await get_meta(organization_id, workflow_id, definition_id)
    summaries = dict(meta.get("ai_summaries") or {})
    summaries[str(diff["base"]["id"])] = summary
    meta["ai_summaries"] = summaries
    await _save_meta(organization_id, workflow_id, definition_id, meta)
    return summary


# --- Restore ------------------------------------------------------------------


class DraftExists(Exception):
    def __init__(self, draft: Any):
        self.draft = draft


async def restore(
    workflow_id: int,
    definition_id: int,
    user: Any,
    *,
    organization_id: int,
    replace_draft: bool = False,
    note: str | None = None,
) -> Any:
    """New draft holding the content of an earlier version.

    The published version is untouched until the draft is published. An
    existing draft is only thrown away with ``replace_draft``.
    """
    source = await brand_db.get_workflow_version(workflow_id, definition_id)
    if source is None:
        raise LookupError("version not found")
    draft = await db_client.get_draft_version(workflow_id)
    if draft is not None:
        if draft.id == source.id:
            raise ValueError("this version is the current draft")
        if not replace_draft:
            raise DraftExists(draft)
        await discard_draft(workflow_id, organization_id=organization_id)
    restored = await db_client.revert_to_version(workflow_id, definition_id)
    await record_edit(
        restored,
        user,
        organization_id=organization_id,
        origin="restore",
        restored_from=source.version_number,
        note=note or f"Restored from v{source.version_number}",
    )
    return restored


async def discard_draft(workflow_id: int, *, organization_id: int) -> None:
    """Throw the draft away, with its metadata."""
    draft = await db_client.get_draft_version(workflow_id)
    await db_client.discard_workflow_draft(workflow_id)
    if draft is not None:
        await brand_db.delete_configuration(
            organization_id, _key(workflow_id, draft.id)
        )

"""Structured diff between two versions of an agent.

A version is the agent graph (``workflow_json``: nodes + edges), its
configuration (``workflow_configurations``: speaking plan, idle timeout, model
overrides…) and its template variables. The diff is computed on the masked
values, so secrets never leave the server.

Output (JSON-ready):
    changes  one entry per added / removed / changed node, edge, configuration
             key group or variable, each with its field-level before / after
             and, for long texts, a word-level diff
    bullets  a short plain-language summary, one line per change
    counts   {"added", "removed", "changed"}
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

FIELD_LABELS = {
    "name": "Name",
    "prompt": "Prompt",
    "greeting": "Greeting",
    "greeting_type": "Greeting type",
    "allow_interrupt": "Allow interruptions",
    "add_global_prompt": "Add global prompt",
    "extraction_enabled": "Variable extraction",
    "extraction_prompt": "Extraction prompt",
    "extraction_variables": "Extracted variables",
    "tool_uuids": "Tools",
    "document_uuids": "Knowledge base documents",
    "delayed_start": "Delayed start",
    "delayed_start_duration": "Delayed start duration",
    "label": "Label",
    "condition": "Condition",
    "type": "Type",
    "speaking_plan": "Speaking plan",
    "max_user_idle_timeout": "Idle timeout",
    "max_call_duration": "Max call duration",
    "smart_turn_stop_secs": "Smart Turn incomplete timeout",
    "turn_start_strategy": "Interruption strategy",
    "turn_start_min_words": "Interruption words",
    "turn_stop_strategy": "Turn detection",
    "context_compaction_enabled": "Context compaction",
    "call_dispositions": "Call dispositions",
    "dictionary": "Dictionary",
    "ambient_noise_configuration": "Ambient noise",
    "model_overrides": "Model overrides",
    "voice_override": "Voice",
    "performance": "Performance",
}

NODE_TYPE_LABELS = {
    "startCall": "start node",
    "agentNode": "agent node",
    "endCall": "end node",
    "globalNode": "global node",
    "trigger": "trigger",
    "webhook": "webhook",
    "qa": "QA node",
}

LONG_TEXT = 60

# Most telling fields first (bullets show the first few).
FIELD_ORDER = {
    k: i for i, k in enumerate(["name", "prompt", "greeting", "label", "condition"])
}


def _label(key: str) -> str:
    last = key.split(".")[-1]
    base = FIELD_LABELS.get(key) or FIELD_LABELS.get(last)
    if base and "." in key:
        head = key.split(".")[0]
        return f"{FIELD_LABELS.get(head, head)} › {last.replace('_', ' ')}"
    return base or key.replace("_", " ").replace(".", " › ").capitalize()


def word_diff(before: str, after: str) -> list[dict]:
    """Word-level diff: [{op: equal|insert|delete, text}], whitespace kept."""
    # Words keep their trailing whitespace, so spaces never anchor a match.
    a = re.findall(r"^\s+|\S+\s*", before or "")
    b = re.findall(r"^\s+|\S+\s*", after or "")
    out: list[dict] = []

    def push(op: str, text: str):
        if not text:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += text
        else:
            out.append({"op": op, "text": text})

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            push("equal", "".join(a[i1:i2]))
        else:
            push("delete", "".join(a[i1:i2]))
            push("insert", "".join(b[j1:j2]))
    return out


def _is_text(v: Any) -> bool:
    return isinstance(v, str) and (len(v) > LONG_TEXT or "\n" in v)


def _field(key: str, before: Any, after: Any) -> dict:
    entry = {"field": key, "label": _label(key), "before": before, "after": after}
    if _is_text(before) or _is_text(after):
        entry["text_diff"] = word_diff(
            before if isinstance(before, str) else "",
            after if isinstance(after, str) else "",
        )
    return entry


def _flatten(d: Any, prefix: str = "", *, depth: int = 2) -> dict[str, Any]:
    """Nested dicts become dotted keys (2 levels); lists stay values."""
    if not isinstance(d, dict) or depth < 0:
        return {prefix: d} if prefix else {}
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict) and depth > 0 and v:
            out.update(_flatten(v, key, depth=depth - 1))
        else:
            out[key] = v
    return out


def _changed_fields(
    before: dict, after: dict, *, skip: set[str] = frozenset()
) -> list[dict]:
    fb, fa = _flatten(before or {}), _flatten(after or {})
    fields = []
    for key in sorted(
        set(fb) | set(fa), key=lambda k: (FIELD_ORDER.get(k, len(FIELD_ORDER)), k)
    ):
        if key.split(".")[0] in skip:
            continue
        # Performance switches: off (False) differs from unset (default on).
        strict = key.startswith("performance.")
        if (fb.get(key) == fa.get(key)) if strict else _same(fb.get(key), fa.get(key)):
            continue
        fields.append(_field(key, fb.get(key), fa.get(key)))
    return fields


def _same(a: Any, b: Any) -> bool:
    # Unset and empty / false mean the same thing for a setting.
    if a in (None, "", [], {}, False) and b in (None, "", [], {}, False):
        return True
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(
        b, sort_keys=True, default=str
    )


def _nodes(graph: dict) -> dict[str, dict]:
    return {
        str(n.get("id")): n
        for n in (graph or {}).get("nodes") or []
        if n.get("id") is not None
    }


def _node_name(node: dict | None) -> str:
    if not node:
        return "?"
    return str((node.get("data") or {}).get("name") or node.get("id"))


def _edge_key(edge: dict) -> str:
    return str(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}")


def _edge_title(edge: dict, nodes_a: dict, nodes_b: dict) -> str:
    src = _node_name(
        nodes_b.get(str(edge.get("source"))) or nodes_a.get(str(edge.get("source")))
    )
    dst = _node_name(
        nodes_b.get(str(edge.get("target"))) or nodes_a.get(str(edge.get("target")))
    )
    label = (edge.get("data") or {}).get("label")
    return f"{src} → {dst}" + (f" ({label})" if label else "")


def _short(v: Any, n: int = 60) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    if v is None or v == "":
        return "—"
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _field_bullet(f: dict, group: str | None = None) -> str:
    label = f["label"]
    if group and f["field"].startswith(group + "."):
        label = f["field"][len(group) + 1 :].replace("_", " ").replace(".", " › ")
    f = {**f, "label": label}
    if "text_diff" in f:
        ins = sum(len(x["text"].split()) for x in f["text_diff"] if x["op"] == "insert")
        dele = sum(
            len(x["text"].split()) for x in f["text_diff"] if x["op"] == "delete"
        )
        return f"{f['label']} rewritten (+{ins} / −{dele} words)"
    return f"{f['label']}: {_short(f['before'], 30)} → {_short(f['after'], 30)}"


def diff_versions(base: dict | None, target: dict) -> dict:
    """Diff two versions: each a dict with workflow_json, workflow_configurations,
    template_context_variables. ``base`` None means the first version."""
    base = base or {}
    ga, gb = base.get("workflow_json") or {}, target.get("workflow_json") or {}
    na, nb = _nodes(ga), _nodes(gb)
    changes: list[dict] = []
    bullets: list[str] = []

    for nid in [*nb.keys(), *[k for k in na if k not in nb]]:
        a, b = na.get(nid), nb.get(nid)
        kind_label = NODE_TYPE_LABELS.get((b or a or {}).get("type"), "node")
        if a is None:
            changes.append(
                {
                    "scope": "node",
                    "kind": "added",
                    "id": nid,
                    "title": _node_name(b),
                    "node_type": b.get("type"),
                    "fields": _changed_fields({}, b.get("data") or {}),
                }
            )
            bullets.append(f"Added {kind_label} “{_node_name(b)}”")
        elif b is None:
            changes.append(
                {
                    "scope": "node",
                    "kind": "removed",
                    "id": nid,
                    "title": _node_name(a),
                    "node_type": a.get("type"),
                    "fields": _changed_fields(a.get("data") or {}, {}),
                }
            )
            bullets.append(f"Removed {kind_label} “{_node_name(a)}”")
        else:
            fields = _changed_fields(a.get("data") or {}, b.get("data") or {})
            if a.get("type") != b.get("type"):
                fields.insert(0, _field("type", a.get("type"), b.get("type")))
            if fields:
                changes.append(
                    {
                        "scope": "node",
                        "kind": "changed",
                        "id": nid,
                        "title": _node_name(b),
                        "node_type": b.get("type"),
                        "fields": fields,
                    }
                )
                bullets.append(
                    f"“{_node_name(b)}”: "
                    + "; ".join(_field_bullet(f) for f in fields[:3])
                    + (f" (+{len(fields) - 3} more)" if len(fields) > 3 else "")
                )

    ea = {_edge_key(e): e for e in ga.get("edges") or []}
    eb = {_edge_key(e): e for e in gb.get("edges") or []}
    for eid in [*eb.keys(), *[k for k in ea if k not in eb]]:
        a, b = ea.get(eid), eb.get(eid)
        if a is None:
            changes.append(
                {
                    "scope": "edge",
                    "kind": "added",
                    "id": eid,
                    "title": _edge_title(b, na, nb),
                    "fields": _changed_fields({}, b.get("data") or {}),
                }
            )
            bullets.append(f"Added transition {_edge_title(b, na, nb)}")
        elif b is None:
            changes.append(
                {
                    "scope": "edge",
                    "kind": "removed",
                    "id": eid,
                    "title": _edge_title(a, na, nb),
                    "fields": _changed_fields(a.get("data") or {}, {}),
                }
            )
            bullets.append(f"Removed transition {_edge_title(a, na, nb)}")
        else:
            fields = _changed_fields(a.get("data") or {}, b.get("data") or {})
            for end in ("source", "target"):
                if str(a.get(end)) != str(b.get(end)):
                    fields.insert(
                        0,
                        _field(
                            end,
                            _node_name(na.get(str(a.get(end)))),
                            _node_name(nb.get(str(b.get(end)))),
                        ),
                    )
            if fields:
                changes.append(
                    {
                        "scope": "edge",
                        "kind": "changed",
                        "id": eid,
                        "title": _edge_title(b, na, nb),
                        "fields": fields,
                    }
                )
                bullets.append(
                    f"Transition {_edge_title(b, na, nb)}: "
                    + "; ".join(_field_bullet(f) for f in fields[:2])
                )

    first = not base
    ca, cb = (
        base.get("workflow_configurations") or {},
        target.get("workflow_configurations") or {},
    )
    # The first version: its graph is the news, not every default setting.
    for group in [] if first else sorted(set(ca) | set(cb)):
        fields = _changed_fields({group: ca.get(group)}, {group: cb.get(group)})
        if not fields:
            continue
        kind = (
            "added" if group not in ca else "removed" if group not in cb else "changed"
        )
        changes.append(
            {
                "scope": "config",
                "kind": kind,
                "id": group,
                "title": _label(group),
                "fields": fields,
            }
        )
        if len(fields) == 1 and fields[0]["field"] == group:
            f = fields[0]
            bullets.append(
                f"Settings › {_label(group)}: "
                f"{_short(f['before'], 30) if f['before'] is not None else 'default'}"
                f" → {_short(f['after'], 30) if f['after'] is not None else 'default'}"
            )
        else:
            bullets.append(
                f"Settings › {_label(group)}: "
                + "; ".join(_field_bullet(f, group) for f in fields[:3])
                + (f" (+{len(fields) - 3} more)" if len(fields) > 3 else "")
            )

    va, vb = (
        base.get("template_context_variables") or {},
        target.get("template_context_variables") or {},
    )
    vfields = [] if first else _changed_fields(va, vb)
    if vfields:
        changes.append(
            {
                "scope": "variables",
                "kind": "changed",
                "id": "variables",
                "title": "Template variables",
                "fields": vfields,
            }
        )
        bullets.append(
            "Template variables: " + ", ".join(f["label"] for f in vfields[:5])
        )

    layout_only = not changes and base and _layout_changed(ga, gb)
    counts = {
        k: sum(1 for c in changes if c["kind"] == k)
        for k in ("added", "removed", "changed")
    }
    return {
        "changes": changes,
        "bullets": (
            bullets
            if changes
            else (["Layout only (nodes moved)"] if layout_only else [])
        ),
        "counts": counts,
        "identical": not changes and not layout_only,
    }


def _layout_changed(ga: dict, gb: dict) -> bool:
    pa = {str(n.get("id")): n.get("position") for n in ga.get("nodes") or []}
    pb = {str(n.get("id")): n.get("position") for n in gb.get("nodes") or []}
    return pa != pb

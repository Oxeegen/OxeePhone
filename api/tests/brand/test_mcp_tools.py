"""OxeePhone: MCP tools for an external agent (analysis, fixes, versions)."""

import api.mcp_server  # noqa: F401  (the package first, as the app does)
from api.brand import mcp_tools


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, fn, annotations=None):
        self.tools[fn.__name__] = annotations


def test_publish_tools_need_the_flag(monkeypatch):
    monkeypatch.setattr(mcp_tools, "CAN_PUBLISH", False)
    mcp = _FakeMCP()
    mcp_tools.register(mcp)
    assert "oxee_apply_fix" in mcp.tools and "oxee_simulate_fix" in mcp.tools
    assert (
        "oxee_publish_draft" not in mcp.tools and "oxee_rollback_fix" not in mcp.tools
    )
    assert mcp.tools["oxee_get_fix"].readOnlyHint is True

    monkeypatch.setattr(mcp_tools, "CAN_PUBLISH", True)
    mcp = _FakeMCP()
    mcp_tools.register(mcp)
    assert mcp.tools["oxee_publish_draft"].destructiveHint is True


def test_fix_view_is_compact():
    fix = {
        "id": "f1",
        "status": "tested",
        "finding": {
            "id": "r6",
            "rule": "dead_air_caller",
            "title": "t",
            "agent": "a",
            "node": None,
            "calls": [1],
        },
        "proposal": {
            "summary": "s",
            "operations": [{"op": "set_setting"}],
            "risks": [],
        },
        "simulation": {
            "status": "done",
            "verdict": "pass",
            "cases": [
                {
                    "case": 1,
                    "baseline": {"path": ["A"], "transcript": ["long"]},
                    "candidate": {"path": ["A", "B"], "transcript": ["long"]},
                }
            ],
        },
    }
    view = mcp_tools._fix_view(fix)
    assert "operations" not in view["proposal"]
    assert view["simulation"]["cases"][0]["draft_path"] == ["A", "B"]
    assert "transcript" not in str(view)
    assert mcp_tools._fix_view(fix, full=True)["proposal"]["operations"] == [
        {"op": "set_setting"}
    ]


def test_test_campaign_tools_follow_the_flag(monkeypatch):
    from api.brand import config

    mcp = _FakeMCP()
    mcp_tools.register(mcp)
    assert mcp.tools["oxee_get_test_execution"].readOnlyHint is True
    assert mcp.tools["oxee_run_test_campaign"].readOnlyHint is False

    monkeypatch.setattr(
        config, "BRAND", config.BrandConfig(**{**config.BRAND.__dict__, "test_campaigns": False})
    )
    mcp = _FakeMCP()
    mcp_tools.register(mcp)
    assert "oxee_run_test_campaign" not in mcp.tools


def test_test_call_view_lists_what_failed():
    from api.brand.mcp_test_tools import _call_view

    view = _call_view(
        {
            "index": 3,
            "scenario_id": "s1",
            "scenario": {"title": "RDV"},
            "status": "done",
            "verdict": "fail",
            "judge": {
                "criteria": [{"text": "a", "pass": True}, {"text": "b", "pass": False}],
                "forbidden": [{"text": "c", "violated": True}],
                "issues": ["x"],
            },
            "checks": [{"label": "Calls book", "pass": False}],
        }
    )
    assert view["failed_criteria"] == ["b"] and view["violated"] == ["c"]
    assert view["failed_checks"] == ["Calls book"] and view["scenario"] == "RDV"

"""Compare one upstream TradingAgents report with one AlphaDesk TA01 task.

The script deliberately compares auditable structure and provenance instead of
trying to score investment opinions.  It uses only Python's standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


EXPECTED_REPORTS: dict[str, str] = {
    "MARKET_ANALYST": "1_analysts/market.md",
    "SENTIMENT_ANALYST": "1_analysts/sentiment.md",
    "NEWS_ANALYST": "1_analysts/news.md",
    "FUNDAMENTAL_ANALYST": "1_analysts/fundamentals.md",
    "BULL_RESEARCHER": "2_research/bull.md",
    "BEAR_RESEARCHER": "2_research/bear.md",
    "RESEARCH_MANAGER": "2_research/manager.md",
    "TRADER": "3_trading/trader.md",
    "AGGRESSIVE_RISK_ANALYST": "4_risk/aggressive.md",
    "NEUTRAL_RISK_ANALYST": "4_risk/neutral.md",
    "CONSERVATIVE_RISK_ANALYST": "4_risk/conservative.md",
    "PORTFOLIO_MANAGER": "5_portfolio/decision.md",
}

EXPECTED_SOURCE_TYPES = (
    "MiniQMT行情",
    "财务报表",
    "公司公告",
    "新闻",
    "宏观",
    "A股市场情绪",
)


def _read_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"无法读取 AlphaDesk API：{exc}") from exc


def _source_type(source_id: str) -> str:
    if source_id.startswith("market-bar:"):
        return "MiniQMT行情"
    if source_id.startswith("akshare:financial") or source_id.startswith(
        ("akshare:balance", "akshare:cashflow", "akshare:income")
    ):
        return "财务报表"
    if source_id.startswith("akshare:stock-news"):
        return "新闻"
    if source_id.startswith("akshare:company-announcement"):
        return "公司公告"
    if source_id.startswith("akshare:a-share-sentiment"):
        return "A股市场情绪"
    if source_id.startswith("akshare:macro"):
        return "宏观"
    if source_id.startswith("information:"):
        return "AlphaDesk公告/资料"
    return source_id.split(":", maxsplit=1)[0] or "未知"


def compare(upstream_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    artifacts = task.get("artifacts") or []
    by_role = {
        str((item.get("metadata") or {}).get("role")): item
        for item in artifacts
        if (item.get("metadata") or {}).get("role")
    }
    role_rows: list[dict[str, Any]] = []
    for role, relative in EXPECTED_REPORTS.items():
        upstream = upstream_dir / relative
        alpha = by_role.get(role)
        role_rows.append(
            {
                "role": role,
                "upstream_path": relative,
                "upstream_present": upstream.is_file() and upstream.stat().st_size > 0,
                "upstream_chars": len(upstream.read_text(encoding="utf-8"))
                if upstream.is_file()
                else 0,
                "alphadesk_present": bool(alpha and alpha.get("content_markdown")),
                "alphadesk_chars": len(str((alpha or {}).get("content_markdown") or "")),
                "alphadesk_source_ids": list((alpha or {}).get("source_ids") or []),
            }
        )

    events = task.get("events") or []
    completed_tools = [
        event
        for event in events
        if event.get("event_type") == "TOOL_CALL" and event.get("status") == "COMPLETED"
    ]
    failed_tools = [
        event
        for event in events
        if event.get("event_type") == "TOOL_CALL" and event.get("status") == "FAILED"
    ]
    tool_sources = [
        str(source_id)
        for event in completed_tools
        for source_id in (event.get("payload") or {}).get("source_ids", [])
        if source_id
    ]
    source_type_counts = Counter(_source_type(source_id) for source_id in tool_sources)
    missing_source_types = [
        source_type
        for source_type in EXPECTED_SOURCE_TYPES
        if source_type_counts[source_type] == 0
    ]
    upstream_complete = upstream_dir / "complete_report.md"
    upstream_roles = sum(row["upstream_present"] for row in role_rows)
    alpha_roles = sum(row["alphadesk_present"] for row in role_rows)
    return {
        "task_id": task.get("task_id"),
        "ticker": (task.get("instrument") or {}).get("symbol"),
        "status": task.get("status"),
        "engine": {
            "key": task.get("engine_key"),
            "version": task.get("engine_version"),
            "attempt": task.get("execution_attempt"),
            "checkpoint": task.get("checkpoint_key"),
        },
        "role_coverage": {
            "expected": len(EXPECTED_REPORTS),
            "upstream": upstream_roles,
            "alphadesk": alpha_roles,
            "alphadesk_percent": round(alpha_roles / len(EXPECTED_REPORTS) * 100, 2),
        },
        "complete_report": {
            "upstream_present": upstream_complete.is_file(),
            "upstream_chars": len(upstream_complete.read_text(encoding="utf-8"))
            if upstream_complete.is_file()
            else 0,
            "alphadesk_present": bool(task.get("report")),
        },
        "workflow": {
            "event_count": len(events),
            "completed_tool_calls": len(completed_tools),
            "failed_tool_calls": len(failed_tools),
            "failed_tool_names": sorted(
                {str(event.get("tool_name") or "未知工具") for event in failed_tools}
            ),
        },
        "sources": {
            "unique_ids": sorted(set(tool_sources)),
            "type_counts": dict(sorted(source_type_counts.items())),
            "expected_types": list(EXPECTED_SOURCE_TYPES),
            "missing_types": missing_source_types,
            "coverage_percent": round(
                (len(EXPECTED_SOURCE_TYPES) - len(missing_source_types))
                / len(EXPECTED_SOURCE_TYPES)
                * 100,
                2,
            ),
        },
        "roles": role_rows,
    }


def _markdown(result: dict[str, Any]) -> str:
    coverage = result["role_coverage"]
    workflow = result["workflow"]
    lines = [
        "# TA01 同股逐项验收",
        "",
        f"- AlphaDesk 任务：`{result['task_id']}`",
        f"- 股票：`{result['ticker']}`",
        f"- 状态：`{result['status']}`",
        f"- Graph：`{result['engine']['key']}` / `{result['engine']['version']}`",
        f"- 角色覆盖：{coverage['alphadesk']}/{coverage['expected']} "
        f"({coverage['alphadesk_percent']}%)；上游基准 {coverage['upstream']}/{coverage['expected']}",
        f"- 工具调用：成功 {workflow['completed_tool_calls']}，失败 {workflow['failed_tool_calls']}",
        f"- 来源覆盖：{result['sources']['coverage_percent']}%",
        "",
        "## 独立报告",
        "",
        "| 角色 | 上游 | AlphaDesk | 上游字符 | AlphaDesk字符 | AlphaDesk引用数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["roles"]:
        lines.append(
            f"| {row['role']} | {'是' if row['upstream_present'] else '否'} | "
            f"{'是' if row['alphadesk_present'] else '否'} | {row['upstream_chars']} | "
            f"{row['alphadesk_chars']} | {len(row['alphadesk_source_ids'])} |"
        )
    lines.extend(["", "## 来源类型", ""])
    if result["sources"]["type_counts"]:
        for name, count in result["sources"]["type_counts"].items():
            lines.append(f"- {name}：{count} 个来源引用")
    else:
        lines.append("- 未捕获到来源编号（验收不通过）")
    if result["sources"]["missing_types"]:
        lines.append(
            "- 缺失来源（验收不通过）："
            + "、".join(result["sources"]["missing_types"])
        )
    if workflow["failed_tool_names"]:
        lines.extend(["", "## 失败工具", ""])
        lines.extend(f"- {name}" for name in workflow["failed_tool_names"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    upstream_dir = args.upstream_dir.resolve()
    if not (upstream_dir / "complete_report.md").is_file():
        parser.error(f"上游报告目录无效：{upstream_dir}")
    task = _read_json(f"{args.api_base.rstrip('/')}/ai/research-tasks/{args.task_id}")
    result = compare(upstream_dir, task)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    markdown = _markdown(result)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
    print(markdown)
    coverage = result["role_coverage"]
    passed = (
        result["status"] == "COMPLETED"
        and coverage["alphadesk"] == coverage["expected"]
        and not result["sources"]["missing_types"]
        and result["workflow"]["completed_tool_calls"] > 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

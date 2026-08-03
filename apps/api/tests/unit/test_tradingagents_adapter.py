import sys
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pandas as pd

from alphadesk_api.infrastructure import tradingagents_adapter
from alphadesk_api.infrastructure.tradingagents_adapter import (
    GraphTraceCollector,
    TradingAgentsResearchEngine,
    _akshare_call,
    _company_announcements,
    _instrument_tool,
    _qwen_structured_output_compat,
)
from alphadesk_domain.ai_workbench import GraphResearchRunRequest, ResearchDepth
from alphadesk_domain.values import utc_now


def test_read_artifacts_uses_real_tradingagents_report_tree(tmp_path: Path) -> None:
    (tmp_path / "1_analysts").mkdir()
    (tmp_path / "2_research").mkdir()
    (tmp_path / "5_portfolio").mkdir()
    (tmp_path / "1_analysts" / "market.md").write_text(
        "市场分析 [source_id: market-bar:2026-07-31]", encoding="utf-8"
    )
    (tmp_path / "2_research" / "bull.md").write_text("看多论证", encoding="utf-8")
    (tmp_path / "5_portfolio" / "decision.md").write_text(
        "组合经理结论", encoding="utf-8"
    )
    (tmp_path / "complete_report.md").write_text("# 完整报告", encoding="utf-8")
    request = GraphResearchRunRequest(
        task_id=uuid4(),
        model_name="qwen-max",
        ticker="300115.SZ",
        company_name="长盈精密",
        question="分析基本面、技术面和主要风险",
        depth=ResearchDepth.STANDARD,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 31),
        data_snapshot={},
    )
    collector = GraphTraceCollector(deadline=utc_now().replace(year=2099))

    artifacts, complete = TradingAgentsResearchEngine._read_artifacts(
        request, tmp_path, collector
    )

    assert complete == "# 完整报告"
    assert [artifact.artifact_metadata["role"] for artifact in artifacts] == [
        "MARKET_ANALYST",
        "BULL_RESEARCHER",
        "PORTFOLIO_MANAGER",
    ]
    assert artifacts[0].source_ids == ("market-bar:2026-07-31",)


def test_adapter_owned_tool_is_audited_without_langchain_callback() -> None:
    collector = GraphTraceCollector(deadline=utc_now().replace(year=2099))
    tool = _instrument_tool(
        collector,
        "get_stock_data",
        lambda symbol: f"{symbol} [source_id: market-bar:2026-07-31]",
    )

    assert tool("300115.SZ").startswith("300115.SZ")
    assert [(event.tool_name, event.status) for event in collector.events] == [
        ("get_stock_data", "RUNNING"),
        ("get_stock_data", "COMPLETED"),
    ]
    assert collector.events[-1].payload["source_ids"] == ["market-bar:2026-07-31"]


def test_qwen_compat_forwards_extra_body_only_inside_context(monkeypatch) -> None:
    package = ModuleType("tradingagents")
    clients = ModuleType("tradingagents.llm_clients")
    openai_client = SimpleNamespace(_PASSTHROUGH_KWARGS=("timeout", "max_retries"))
    clients.openai_client = openai_client
    package.llm_clients = clients
    monkeypatch.setitem(sys.modules, "tradingagents", package)
    monkeypatch.setitem(sys.modules, "tradingagents.llm_clients", clients)
    original = openai_client._PASSTHROUGH_KWARGS

    with _qwen_structured_output_compat("qwen-cn"):
        assert "extra_body" in openai_client._PASSTHROUGH_KWARGS

    assert original == openai_client._PASSTHROUGH_KWARGS


def test_company_announcements_falls_back_to_eastmoney(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(name: str, **kwargs: object) -> str:
        calls.append((name, kwargs))
        if name == "stock_zh_a_disclosure_report_cninfo":
            return "DATA_UNAVAILABLE: cninfo failed"
        return "代码,名称,公告标题\n300115,长盈精密,权益分派公告"

    monkeypatch.setattr(
        tradingagents_adapter, "_context", lambda: SimpleNamespace(plain_symbol="300115")
    )
    monkeypatch.setattr(tradingagents_adapter, "_akshare_call", fake_call)

    value, source_id = _company_announcements("2026-06-01", "2026-07-28")

    assert "权益分派公告" in value
    assert source_id == "akshare:company-announcement:eastmoney"
    assert [name for name, _ in calls] == [
        "stock_zh_a_disclosure_report_cninfo",
        "stock_individual_notice_report",
    ]
    assert calls[-1][1]["begin_date"] == "20260601"


def test_akshare_call_retries_one_transient_failure(monkeypatch) -> None:
    calls = 0

    def flaky(**kwargs: object) -> pd.DataFrame:
        nonlocal calls
        del kwargs
        calls += 1
        if calls == 1:
            raise KeyError("temporary empty response")
        return pd.DataFrame([{"代码": "300115", "公告标题": "权益分派公告"}])

    fake_akshare = SimpleNamespace(stock_individual_notice_report=flaky)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setattr(
        tradingagents_adapter,
        "_context",
        lambda: SimpleNamespace(external_data_enabled=True),
    )
    monkeypatch.setattr(tradingagents_adapter.time, "sleep", lambda _: None)

    value = _akshare_call("stock_individual_notice_report", security="300115")

    assert calls == 2
    assert "权益分派公告" in value

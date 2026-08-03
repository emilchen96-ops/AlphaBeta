"""Legal, runtime-independent TradingAgents Graph adapter for TA01.

The upstream package remains an explicitly pinned Apache-2.0 dependency.  This
module only adapts AlphaDesk's immutable task snapshot to upstream tool routes
and translates the completed graph state into durable AlphaDesk artifacts.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # Keep pure adapter unit tests independent of the optional Graph runtime.
    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass

from alphadesk_api.core.config import Settings
from alphadesk_domain.ai_workbench import (
    GraphResearchRunError,
    GraphResearchRunRequest,
    GraphResearchRunResult,
    MultiAgentResearchArtifact,
    MultiAgentResearchWorkflowEvent,
    ResearchAgentRole,
    ResearchDepth,
)

LOGGER = logging.getLogger(__name__)
UPSTREAM_REVISION = "a33fd4c0f134485a43553a2c23a63cb14adbd88f"
_SOURCE_ID = re.compile(r"(?:source_id\s*[:=]\s*|\[source_id:\s*)([\w:./-]+)")
_RUN_CONTEXT: contextvars.ContextVar[AlphaDeskToolContext | None] = contextvars.ContextVar(
    "alphadesk_tradingagents_run", default=None
)


def _json_safe(value: object, *, limit: int = 20_000) -> object:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = repr(value)
    if len(raw) > limit:
        raw = raw[:limit] + "…[truncated]"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _source_ids(value: object) -> tuple[str, ...]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return tuple(dict.fromkeys(_SOURCE_ID.findall(text)))


@dataclass(slots=True)
class TraceEntry:
    sequence: int
    event_type: str
    status: str
    node_name: str = ""
    tool_name: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GraphTraceCollector(BaseCallbackHandler):
    """LangChain callback compatible collector with bounded payloads."""

    def __init__(self, *, deadline: datetime) -> None:
        super().__init__()
        self._deadline = deadline
        self._lock = threading.Lock()
        self._events: list[TraceEntry] = []
        self._starts: dict[str, tuple[datetime, str]] = {}
        self.input_tokens = 0
        self.output_tokens = 0

    def _check_deadline(self) -> None:
        if datetime.now(UTC) >= self._deadline:
            raise TimeoutError("TradingAgents Graph exceeded the configured task timeout")

    def _append(self, **values: object) -> None:
        self._check_deadline()
        with self._lock:
            if len(self._events) >= 4_000:
                return
            self._events.append(TraceEntry(sequence=len(self._events), **values))  # type: ignore[arg-type]

    @staticmethod
    def _name(serialized: object, fallback: str) -> str:
        if isinstance(serialized, Mapping):
            value = serialized.get("name")
            if value:
                return str(value)
            identifier = serialized.get("id")
            if isinstance(identifier, list) and identifier:
                return str(identifier[-1])
        return fallback

    def on_tool_start(
        self,
        serialized: object,
        input_str: str,
        *,
        run_id: object,
        inputs: object | None = None,
        **_: object,
    ) -> None:
        now = datetime.now(UTC)
        tool_name = self._name(serialized, "unknown_tool")
        self._starts[str(run_id)] = (now, tool_name)
        self._append(
            event_type="TOOL_CALL",
            status="RUNNING",
            node_name="tool",
            tool_name=tool_name,
            payload={"input": _json_safe(inputs if inputs is not None else input_str)},
            started_at=now,
        )

    def on_tool_end(self, output: object, *, run_id: object, **_: object) -> None:
        now = datetime.now(UTC)
        started_at, tool_name = self._starts.pop(str(run_id), (None, "unknown_tool"))
        self._append(
            event_type="TOOL_CALL",
            status="COMPLETED",
            node_name="tool",
            tool_name=tool_name,
            payload={"output": _json_safe(output), "source_ids": list(_source_ids(output))},
            started_at=started_at,
            completed_at=now,
        )

    def on_tool_error(self, error: BaseException, *, run_id: object, **_: object) -> None:
        now = datetime.now(UTC)
        started_at, tool_name = self._starts.pop(str(run_id), (None, "unknown_tool"))
        self._append(
            event_type="TOOL_CALL",
            status="FAILED",
            node_name="tool",
            tool_name=tool_name,
            payload={"error": str(error)[:2000]},
            started_at=started_at,
            completed_at=now,
        )

    def on_chain_start(
        self, serialized: object, inputs: object, *, run_id: object, **_: object
    ) -> None:
        now = datetime.now(UTC)
        self._starts[str(run_id)] = (now, self._name(serialized, "langgraph_node"))
        self._append(
            event_type="GRAPH_NODE",
            status="RUNNING",
            node_name=self._name(serialized, "langgraph_node"),
            payload={"input": _json_safe(inputs, limit=4000)},
            started_at=now,
        )

    def on_chain_end(self, outputs: object, *, run_id: object, **_: object) -> None:
        now = datetime.now(UTC)
        started_at, node_name = self._starts.pop(str(run_id), (None, "langgraph_node"))
        self._append(
            event_type="GRAPH_NODE",
            status="COMPLETED",
            node_name=node_name,
            payload={"output": _json_safe(outputs, limit=4000)},
            started_at=started_at,
            completed_at=now,
        )

    def on_chain_error(self, error: BaseException, *, run_id: object, **_: object) -> None:
        now = datetime.now(UTC)
        started_at, node_name = self._starts.pop(str(run_id), (None, "langgraph_node"))
        self._append(
            event_type="GRAPH_NODE",
            status="FAILED",
            node_name=node_name,
            payload={"error": str(error)[:2000]},
            started_at=started_at,
            completed_at=now,
        )

    def on_llm_end(self, response: object, **_: object) -> None:
        usage = getattr(response, "llm_output", None)
        if isinstance(usage, Mapping):
            token_usage = usage.get("token_usage") or usage.get("usage") or {}
            if isinstance(token_usage, Mapping):
                self.input_tokens += int(
                    token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
                )
                self.output_tokens += int(
                    token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
                )

    @property
    def events(self) -> tuple[TraceEntry, ...]:
        with self._lock:
            return tuple(self._events)

    def call_tool(
        self,
        tool_name: str,
        function: Callable[..., str],
        *args: object,
        **kwargs: object,
    ) -> str:
        """Audit adapter-owned tools even when upstream callbacks are not propagated."""

        started_at = datetime.now(UTC)
        self._append(
            event_type="TOOL_CALL",
            status="RUNNING",
            node_name="alphadesk_adapter",
            tool_name=tool_name,
            payload={"input": _json_safe({"args": args, "kwargs": kwargs}, limit=4000)},
            started_at=started_at,
        )
        try:
            output = function(*args, **kwargs)
        except Exception as exc:
            self._append(
                event_type="TOOL_CALL",
                status="FAILED",
                node_name="alphadesk_adapter",
                tool_name=tool_name,
                payload={"error": str(exc)[:2000]},
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            raise
        self._append(
            event_type="TOOL_CALL",
            status="COMPLETED",
            node_name="alphadesk_adapter",
            tool_name=tool_name,
            payload={"output": _json_safe(output), "source_ids": list(_source_ids(output))},
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        return output


def _instrument_tool(
    collector: GraphTraceCollector,
    tool_name: str,
    function: Callable[..., str],
) -> Callable[..., str]:
    @wraps(function)
    def traced(*args: object, **kwargs: object) -> str:
        return collector.call_tool(tool_name, function, *args, **kwargs)

    return traced


@dataclass(slots=True)
class AlphaDeskToolContext:
    request: GraphResearchRunRequest
    external_data_enabled: bool

    @property
    def bars(self) -> list[dict[str, object]]:
        value = self.request.data_snapshot.get("market_bars", [])
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @property
    def information(self) -> list[dict[str, object]]:
        value = self.request.data_snapshot.get("information", [])
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @property
    def plain_symbol(self) -> str:
        return self.request.ticker.split(".", maxsplit=1)[0]


def _context() -> AlphaDeskToolContext:
    value = _RUN_CONTEXT.get()
    if value is None:
        raise RuntimeError("AlphaDesk TradingAgents tool called outside a research task")
    return value


def _bars_frame() -> pd.DataFrame:
    rows = _context().bars
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame.sort_values("date").dropna(subset=["date"])


def _market_data(symbol: str, start_date: str, end_date: str) -> str:
    del symbol
    frame = _bars_frame()
    if not frame.empty:
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    lines = [
        f"# AlphaDesk MiniQMT A股日线：{_context().request.company_name}",
        "唯一行情来源：MiniQMT 本地只读行情；价格口径：不复权。",
    ]
    for row in frame.to_dict("records"):
        day = pd.Timestamp(row["date"]).date().isoformat()
        lines.append(
            f"{day} O={row.get('open')} H={row.get('high')} L={row.get('low')} "
            f"C={row.get('close')} V={row.get('volume')} A={row.get('amount')} "
            f"[source_id: market-bar:{day}]"
        )
    return "\n".join(lines)


def _indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    del symbol
    frame = _bars_frame()
    frame = frame[frame["date"] <= pd.Timestamp(curr_date)].tail(max(look_back_days, 260)).copy()
    if frame.empty:
        return "NO_DATA_AVAILABLE: AlphaDesk MiniQMT 本地行情为空。"
    close = frame["close"]
    name = indicator.lower().strip()
    if "rsi" in name:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        values = 100 - (100 / (1 + gain / loss.replace(0, pd.NA)))
    elif "macd" in name:
        values = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    elif "atr" in name:
        previous = close.shift(1)
        tr = pd.concat(
            [
                frame["high"] - frame["low"],
                (frame["high"] - previous).abs(),
                (frame["low"] - previous).abs(),
            ],
            axis=1,
        ).max(axis=1)
        values = tr.rolling(14).mean()
    elif "ema" in name:
        period = next((int(item) for item in re.findall(r"\d+", name)), 20)
        values = close.ewm(span=period, adjust=False).mean()
    else:
        period = next((int(item) for item in re.findall(r"\d+", name)), 20)
        values = close.rolling(period).mean()
    lines = [f"# {indicator}（基于 AlphaDesk MiniQMT 日线计算）"]
    for timestamp, value in values.dropna().tail(look_back_days).items():
        day = pd.Timestamp(frame.loc[timestamp, "date"]).date().isoformat()
        lines.append(f"{day}: {float(value):.6f} [source_id: market-bar:{day}]")
    return "\n".join(lines)


def _verified_snapshot(symbol: str, curr_date: str, look_back_days: int = 30) -> str:
    del symbol
    frame = _bars_frame()
    frame = frame[frame["date"] <= pd.Timestamp(curr_date)].tail(look_back_days)
    if frame.empty:
        return "NO_DATA_AVAILABLE: AlphaDesk MiniQMT 本地行情为空。"
    latest = frame.iloc[-1]
    day = pd.Timestamp(latest["date"]).date().isoformat()
    recent = ", ".join(f"{value:.3f}" for value in frame["close"].tail(10))
    return (
        f"VERIFIED_MINIQMT_SNAPSHOT {day}: open={latest['open']}, high={latest['high']}, "
        f"low={latest['low']}, close={latest['close']}, volume={latest['volume']}; "
        f"recent_closes=[{recent}] [source_id: market-bar:{day}]"
    )


def _local_information(kind: str) -> str:
    context = _context()
    lines = [f"# AlphaDesk {kind}资料：{context.request.company_name}"]
    for item in context.information:
        source_id = str(item.get("source_id") or "information:unknown")
        lines.append(
            f"## {item.get('title') or '未命名资料'}\n"
            f"发布时间：{item.get('published_at') or '未知'}\n"
            f"{str(item.get('content') or '')[:6000]}\n[source_id: {source_id}]"
        )
    if len(lines) == 1:
        lines.append("DATA_UNAVAILABLE: AlphaDesk 本地没有对应资料，不得编造。")
    return "\n\n".join(lines)


def _akshare_call(name: str, **kwargs: object) -> str:
    context = _context()
    if not context.external_data_enabled:
        return "DATA_UNAVAILABLE: 外部资料抓取已禁用。"
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            import akshare as ak  # type: ignore[import-untyped]

            function = getattr(ak, name)
            result = function(**kwargs)
            text = (
                result.head(200).to_csv(index=False)
                if hasattr(result, "to_csv")
                else str(result)
            )
            return text[:60_000]
        except Exception as exc:  # external provider degradation is explicit
            last_error = exc
            if attempt == 1:
                LOGGER.info("AkShare tool %s transient failure; retrying: %s", name, exc)
                time.sleep(0.75)
    LOGGER.warning("AkShare tool %s failed after retry: %s", name, last_error)
    return f"DATA_UNAVAILABLE: {name} 获取失败（{last_error}），不得编造。"


def _external_source(value: str, source_id: str) -> str:
    """Attach provenance only when the external provider returned real data."""

    return (
        ""
        if not value.strip() or value.startswith("DATA_UNAVAILABLE:")
        else f"\n[source_id: {source_id}]"
    )


def _company_announcements(start_date: str, end_date: str) -> tuple[str, str]:
    """Fetch company announcements with an independent provider fallback."""

    context = _context()
    primary = _akshare_call(
        "stock_zh_a_disclosure_report_cninfo",
        symbol=context.plain_symbol,
        market="沪深京",
        keyword="",
        category="",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    if not primary.startswith("DATA_UNAVAILABLE:"):
        return primary, "akshare:company-announcement:cninfo"
    fallback = _akshare_call(
        "stock_individual_notice_report",
        security=context.plain_symbol,
        symbol="全部",
        begin_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    if not fallback.startswith("DATA_UNAVAILABLE:"):
        return fallback, "akshare:company-announcement:eastmoney"
    return f"{primary}\n{fallback}", ""


def _fundamentals(ticker: str, curr_date: str) -> str:
    del ticker, curr_date
    local = _local_information("财务与公告")
    external = _akshare_call("stock_financial_abstract_ths", symbol=_context().plain_symbol)
    return (
        f"{local}\n\n# AkShare 财务摘要\n{external}"
        f"{_external_source(external, 'akshare:financial-abstract')}"
    )


def _statement(statement: str) -> str:
    function = {
        "balance": "stock_balance_sheet_by_report_em",
        "cashflow": "stock_cash_flow_sheet_by_report_em",
        "income": "stock_profit_sheet_by_report_em",
    }[statement]
    plain = _context().plain_symbol
    prefix = (
        "SH"
        if plain.startswith(("5", "6", "9"))
        else "BJ"
        if plain.startswith(("4", "8"))
        else "SZ"
    )
    external = _akshare_call(function, symbol=f"{prefix}{plain}")
    return (
        f"# AkShare {statement}\n{external}"
        f"{_external_source(external, f'akshare:{statement}')}"
    )


def _news(ticker: str, start_date: str, end_date: str) -> str:
    del ticker
    local = _local_information("新闻与公告")
    external = _akshare_call("stock_news_em", symbol=_context().plain_symbol)
    announcement, announcement_source_id = _company_announcements(start_date, end_date)
    announcement_source = _external_source(announcement, announcement_source_id)
    news_source = _external_source(external, "akshare:stock-news")
    return (
        f"{local}\n\n# AkShare 个股新闻\n{external}{news_source}\n\n"
        f"# 公司公告（巨潮资讯，失败时回退东方财富）\n"
        f"{announcement}{announcement_source}"
    )


def _global_news(curr_date: str, look_back_days: int, limit: int = 20) -> str:
    del curr_date, look_back_days, limit
    cpi = _akshare_call("macro_china_cpi_yearly")
    gdp = _akshare_call("macro_china_gdp")
    cpi_source = _external_source(cpi, "akshare:macro:cpi")
    gdp_source = _external_source(gdp, "akshare:macro:gdp")
    return (
        f"{_local_information('市场与宏观新闻')}\n\n"
        f"# 中国CPI\n{cpi}{cpi_source}\n\n# 中国GDP\n{gdp}{gdp_source}"
    )


def _insider(ticker: str) -> str:
    del ticker
    return _local_information("股东及高管变动") + "\n[source_id: alphadesk:insider-information]"


def _macro(indicator: str, curr_date: str, look_back_days: int) -> str:
    del curr_date, look_back_days
    function = "macro_china_cpi_yearly" if "cpi" in indicator.lower() else "macro_china_gdp"
    external = _akshare_call(function)
    return (
        f"# AkShare 中国宏观指标 {indicator}\n{external}"
        f"{_external_source(external, f'akshare:macro:{function}')}"
    )


def _prediction(topic: str, limit: int = 20) -> str:
    del topic, limit
    return "DATA_UNAVAILABLE: A股研究未配置预测市场资料，不得编造。"


def _a_share_sentiment_news(ticker: str, limit: int = 30) -> str:
    """Provide A-share sentiment evidence without US social-media fallbacks."""

    del ticker, limit
    local = _local_information("A股公告、新闻与市场情绪")
    external = _akshare_call("stock_news_em", symbol=_context().plain_symbol)
    return (
        f"{local}\n\n# AkShare A股个股新闻与市场情绪素材\n{external}"
        f"{_external_source(external, 'akshare:a-share-sentiment-news')}"
    )


def _a_share_market_sentiment(ticker: str) -> str:
    """Derive a bounded, auditable market-behaviour signal from MiniQMT bars."""

    del ticker
    frame = _bars_frame().tail(20)
    if frame.empty:
        return "DATA_UNAVAILABLE: AlphaDesk MiniQMT 本地行情为空，不得编造市场情绪。"
    first = frame.iloc[0]
    latest = frame.iloc[-1]
    first_close = float(first["close"])
    latest_close = float(latest["close"])
    change = (latest_close / first_close - 1) * 100 if first_close else 0.0
    volume = frame["volume"].dropna()
    recent_volume = float(volume.tail(5).mean()) if not volume.empty else 0.0
    prior_volume = float(volume.head(max(len(volume) - 5, 1)).mean()) if not volume.empty else 0.0
    volume_ratio = recent_volume / prior_volume if prior_volume else 0.0
    start = pd.Timestamp(first["date"]).date().isoformat()
    end = pd.Timestamp(latest["date"]).date().isoformat()
    return (
        "# MiniQMT A股市场行为情绪代理\n"
        f"区间：{start} 至 {end}；收盘价变化：{change:.2f}%；"
        f"近5日平均成交量/此前区间平均成交量：{volume_ratio:.3f}。\n"
        "该结果仅是价格与成交量行为代理，不等同于投资者调查或社交媒体情绪。\n"
        f"[source_id: market-bar:{start}] [source_id: market-bar:{end}]"
    )


def _build_a_share_sentiment_prompt(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Relabel upstream sentiment inputs to their actual A-share evidence."""

    return f"""你是A股市场情绪分析师。请分析 {ticker} 在 {start_date} 至 {end_date} 的市场情绪。

以下资料已由 AlphaDesk 预先采集；不得声称使用了 StockTwits、Reddit、X 或其他未提供的平台。

## 财经新闻、公司公告与公开市场资料
<start_of_news>
{news_block}
<end_of_news>

## A股个股新闻与情绪素材
<start_of_a_share_sentiment>
{stocktwits_block}
<end_of_a_share_sentiment>

## MiniQMT 价格与成交量行为代理
<start_of_market_behaviour>
{reddit_block}
<end_of_market_behaviour>

请区分事实、市场行为代理和推断，逐项保留 source_id。若资料缺失必须明确写出，不得编造。
输出应包含：overall_band（Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish）、
overall_score（0至10）、confidence（low / medium / high）和 narrative。narrative 用简体中文说明
主要情绪方向、证据、分歧、催化剂、风险和资料限制。历史情绪不是未来价格保证。"""


@contextmanager
def _upstream_environment(api_key: str, provider: str):
    key_name = {
        "qwen-cn": "DASHSCOPE_CN_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider, "OPENAI_COMPATIBLE_API_KEY")
    old = os.environ.get(key_name)
    os.environ[key_name] = api_key
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key_name, None)
        else:
            os.environ[key_name] = old


@contextmanager
def _qwen_structured_output_compat(provider: str):
    """Pass DashScope's non-thinking flag through the pinned upstream client.

    TradingAgents intentionally allow-lists ChatOpenAI constructor arguments.
    Revision ``UPSTREAM_REVISION`` does not yet include ``extra_body``, while
    DashScope rejects LangChain's structured ``tool_choice`` in thinking mode.
    The shim is process-local, provider-scoped, and always restored.
    """

    if provider not in {"qwen", "qwen-cn"}:
        yield
        return
    from tradingagents.llm_clients import openai_client

    previous = openai_client._PASSTHROUGH_KWARGS
    if "extra_body" not in previous:
        openai_client._PASSTHROUGH_KWARGS = (*previous, "extra_body")
    try:
        yield
    finally:
        openai_client._PASSTHROUGH_KWARGS = previous


ARTIFACT_ROLE: dict[str, ResearchAgentRole] = {
    "1_analysts/market.md": ResearchAgentRole.MARKET_ANALYST,
    "1_analysts/sentiment.md": ResearchAgentRole.SENTIMENT_ANALYST,
    "1_analysts/news.md": ResearchAgentRole.NEWS_ANALYST,
    "1_analysts/fundamentals.md": ResearchAgentRole.FUNDAMENTAL_ANALYST,
    "2_research/bull.md": ResearchAgentRole.BULL_RESEARCHER,
    "2_research/bear.md": ResearchAgentRole.BEAR_RESEARCHER,
    "2_research/manager.md": ResearchAgentRole.RESEARCH_MANAGER,
    "3_trading/trader.md": ResearchAgentRole.TRADER,
    "4_risk/aggressive.md": ResearchAgentRole.AGGRESSIVE_RISK_ANALYST,
    "4_risk/neutral.md": ResearchAgentRole.NEUTRAL_RISK_ANALYST,
    "4_risk/conservative.md": ResearchAgentRole.CONSERVATIVE_RISK_ANALYST,
    "5_portfolio/decision.md": ResearchAgentRole.PORTFOLIO_MANAGER,
}


class TradingAgentsResearchEngine:
    """Run the upstream Graph in a dedicated worker process."""

    configured = True

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.configured = bool(settings.ai_api_key and settings.ai_model)

    async def run(self, request: GraphResearchRunRequest) -> GraphResearchRunResult:
        if not self.configured:
            raise RuntimeError("TradingAgents Graph requires a configured AI provider")
        timeout = self._settings.ai_graph_timeout_seconds
        return await asyncio.wait_for(
            asyncio.to_thread(self._run_sync, request), timeout=timeout + 30
        )

    def _run_sync(self, request: GraphResearchRunRequest) -> GraphResearchRunResult:
        try:
            from tradingagents.agents.analysts import sentiment_analyst
            from tradingagents.dataflows import interface, market_data_validator
            from tradingagents.graph import trading_graph
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:
            raise RuntimeError(
                "TRADINGAGENTS_NOT_INSTALLED: install the pinned TradingAgents dependency"
            ) from exc

        deadline = datetime.fromtimestamp(
            datetime.now(UTC).timestamp() + self._settings.ai_graph_timeout_seconds,
            tz=UTC,
        )
        collector = GraphTraceCollector(deadline=deadline)
        context = AlphaDeskToolContext(
            request=request,
            external_data_enabled=self._settings.ai_external_data_enabled,
        )
        token = _RUN_CONTEXT.set(context)
        raw_methods: dict[str, Callable[..., str]] = {
            "get_stock_data": _market_data,
            "get_indicators": _indicator,
            "get_fundamentals": _fundamentals,
            "get_balance_sheet": lambda ticker, freq, curr_date: _statement("balance"),
            "get_cashflow": lambda ticker, freq, curr_date: _statement("cashflow"),
            "get_income_statement": lambda ticker, freq, curr_date: _statement("income"),
            "get_news": _news,
            "get_global_news": _global_news,
            "get_insider_transactions": _insider,
            "get_macro_indicators": _macro,
            "get_prediction_markets": _prediction,
        }
        methods = {
            name: _instrument_tool(collector, name, function)
            for name, function in raw_methods.items()
        }
        previous_methods: dict[str, object] = {}
        for name, function in methods.items():
            previous_methods[name] = interface.VENDOR_METHODS[name].get("alphadesk")
            interface.VENDOR_METHODS[name]["alphadesk"] = function
        previous_snapshot = market_data_validator.build_verified_market_snapshot
        market_data_validator.build_verified_market_snapshot = _verified_snapshot
        import tradingagents.agents.utils.market_data_validation_tools as validation_tools

        previous_tool_snapshot = validation_tools.build_verified_market_snapshot
        validation_tools.build_verified_market_snapshot = _verified_snapshot
        previous_sentiment_news = sentiment_analyst.fetch_stocktwits_messages
        previous_sentiment_discussion = sentiment_analyst.fetch_reddit_posts
        previous_sentiment_prompt = sentiment_analyst._build_system_message
        sentiment_analyst.fetch_stocktwits_messages = _instrument_tool(
            collector, "get_a_share_sentiment_news", _a_share_sentiment_news
        )
        sentiment_analyst.fetch_reddit_posts = _instrument_tool(
            collector, "get_a_share_market_sentiment", _a_share_market_sentiment
        )
        sentiment_analyst._build_system_message = _build_a_share_sentiment_prompt
        previous_identity = trading_graph.resolve_instrument_identity
        trading_graph.resolve_instrument_identity = lambda ticker: {
            "company_name": request.company_name,
            "exchange": str(request.data_snapshot.get("instrument", {}).get("exchange", ""))
            if isinstance(request.data_snapshot.get("instrument"), dict)
            else "",
        }

        checkpoint_dir = Path(self._settings.ai_checkpoint_dir) / str(request.task_id)
        artifact_dir = Path(self._settings.ai_artifact_dir) / str(request.task_id)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        selected_model = request.model_name.strip()
        quick = selected_model or self._settings.ai_quick_model or self._settings.ai_model or ""
        deep = selected_model or self._settings.ai_deep_model or self._settings.ai_model or quick
        provider = self._provider_key()
        rounds = 2 if request.depth is ResearchDepth.DEEP else 1
        config: dict[str, object] = {
            "project_dir": str(artifact_dir),
            "results_dir": str(artifact_dir),
            "data_cache_dir": str(checkpoint_dir),
            "memory_log_path": str(checkpoint_dir / "memory.md"),
            "memory_log_max_entries": 100,
            "llm_provider": provider,
            "quick_think_llm": quick,
            "deep_think_llm": deep,
            "backend_url": self._settings.ai_base_url,
            "temperature": float(self._settings.ai_temperature),
            "llm_max_retries": self._settings.ai_max_retries,
            "llm_request_timeout": self._settings.ai_request_timeout_seconds,
            "checkpoint_enabled": True,
            "output_language": "Simplified Chinese",
            "max_debate_rounds": min(rounds, self._settings.ai_max_debate_rounds),
            "max_risk_discuss_rounds": min(rounds, self._settings.ai_max_risk_rounds),
            "max_recur_limit": 120,
            "news_article_limit": 30,
            "global_news_article_limit": 20,
            "global_news_lookback_days": 30,
            "global_news_queries": ["中国宏观经济 A股 货币政策 产业政策"],
            "data_vendors": {
                "core_stock_apis": "alphadesk",
                "technical_indicators": "alphadesk",
                "fundamental_data": "alphadesk",
                "news_data": "alphadesk",
                "macro_data": "alphadesk",
                "prediction_markets": "alphadesk",
            },
            "tool_vendors": {name: "alphadesk" for name in methods},
            "benchmark_ticker": None,
            "benchmark_map": {".SS": "000001.SS", ".SZ": "399001.SZ", "": "000001.SS"},
        }
        api_key = self._settings.ai_api_key.get_secret_value() if self._settings.ai_api_key else ""

        class _AlphaDeskGraph(TradingAgentsGraph):  # type: ignore[misc, valid-type]
            def _get_provider_kwargs(inner_self) -> dict[str, Any]:
                values = super()._get_provider_kwargs()
                values["timeout"] = self._settings.ai_request_timeout_seconds
                if provider in {"qwen", "qwen-cn"} and (
                    quick.lower().startswith("qwen") or deep.lower().startswith("qwen")
                ):
                    # DashScope rejects tool_choice=json-schema while thinking
                    # mode is enabled. TradingAgents structured analyst reports
                    # need deterministic schemas more than hidden reasoning.
                    values["extra_body"] = {"enable_thinking": False}
                return values

            def resolve_instrument_context(
                inner_self, ticker: str, asset_type: str = "stock"
            ) -> str:
                base = super().resolve_instrument_context(ticker, asset_type)
                return (
                    f"{base}\n"
                    f"AlphaDesk 用户调研问题：{request.question}\n"
                    f"指定资料范围：{request.start_date.isoformat()} 至 "
                    f"{request.end_date.isoformat()}。"
                    "必须使用工具检索证据，明确区分事实、推断与资料缺口；"
                    "本流程仅用于研究，不生成真实订单。"
                )

        try:
            with _upstream_environment(api_key, provider), _qwen_structured_output_compat(
                provider
            ):
                graph = _AlphaDeskGraph(
                    selected_analysts=("market", "social", "news", "fundamentals"),
                    debug=False,
                    config=config,
                    callbacks=[collector],
                )
                final_state, _ = graph.propagate(request.ticker, request.end_date.isoformat())
                complete_report_path = graph.save_reports(
                    final_state, request.ticker, artifact_dir
                )
            artifacts, complete = self._read_artifacts(
                request, Path(complete_report_path).parent, collector
            )
            source_ids = tuple(
                dict.fromkeys(
                    source_id
                    for event in collector.events
                    for source_id in event.payload.get("source_ids", [])
                    if isinstance(source_id, str)
                )
            )
            events = self._workflow_events(request, collector)
            return GraphResearchRunResult(
                engine_version=UPSTREAM_REVISION,
                checkpoint_key=f"{request.ticker}:{request.end_date}:{request.depth.value}",
                final_decision=str(final_state.get("final_trade_decision") or ""),
                complete_report_markdown=complete,
                artifacts=artifacts,
                events=events,
                source_ids=source_ids,
                input_token_count=collector.input_tokens,
                output_token_count=collector.output_tokens,
            )
        except Exception as exc:
            code = (
                "AI_PROVIDER_REQUEST_TIMEOUT"
                if type(exc).__name__ in {"APITimeoutError", "ReadTimeout", "TimeoutError"}
                else "TRADINGAGENTS_GRAPH_FAILED"
            )
            raise GraphResearchRunError(
                str(exc) or type(exc).__name__,
                code=code,
                checkpoint_key=f"{request.ticker}:{request.end_date}:{request.depth.value}",
                events=self._workflow_events(request, collector),
            ) from exc
        finally:
            _RUN_CONTEXT.reset(token)
            market_data_validator.build_verified_market_snapshot = previous_snapshot
            validation_tools.build_verified_market_snapshot = previous_tool_snapshot
            sentiment_analyst.fetch_stocktwits_messages = previous_sentiment_news
            sentiment_analyst.fetch_reddit_posts = previous_sentiment_discussion
            sentiment_analyst._build_system_message = previous_sentiment_prompt
            trading_graph.resolve_instrument_identity = previous_identity
            for name, previous in previous_methods.items():
                if previous is None:
                    interface.VENDOR_METHODS[name].pop("alphadesk", None)
                else:
                    interface.VENDOR_METHODS[name]["alphadesk"] = previous

    @staticmethod
    def _workflow_events(
        request: GraphResearchRunRequest, collector: GraphTraceCollector
    ) -> tuple[MultiAgentResearchWorkflowEvent, ...]:
        return tuple(
            MultiAgentResearchWorkflowEvent(
                task_id=request.task_id,
                sequence=item.sequence,
                event_type=item.event_type,
                status=item.status,
                node_name=item.node_name,
                tool_name=item.tool_name,
                payload=item.payload,
                started_at=item.started_at,
                completed_at=item.completed_at,
            )
            for item in collector.events
        )

    def _provider_key(self) -> str:
        base = (self._settings.ai_base_url or "").lower()
        if "dashscope.aliyuncs.com" in base:
            return "qwen-cn"
        if "dashscope-intl.aliyuncs.com" in base:
            return "qwen"
        if "api.openai.com" in base or not base:
            return "openai"
        return "openai_compatible"

    @staticmethod
    def _read_artifacts(
        request: GraphResearchRunRequest,
        report_path: Path,
        collector: GraphTraceCollector,
    ) -> tuple[tuple[MultiAgentResearchArtifact, ...], str]:
        files = sorted(report_path.rglob("*.md"))
        artifacts: list[MultiAgentResearchArtifact] = []
        complete = ""
        for ordinal, path in enumerate(files):
            relative = path.relative_to(report_path).as_posix()
            content = path.read_text(encoding="utf-8")
            if relative == "complete_report.md":
                complete = content
                continue
            role = ARTIFACT_ROLE.get(relative)
            artifacts.append(
                MultiAgentResearchArtifact(
                    task_id=request.task_id,
                    artifact_key=relative.removesuffix(".md").replace("/", "."),
                    artifact_type="AGENT_REPORT",
                    title=relative.removesuffix(".md").replace("_", " "),
                    content_markdown=content,
                    ordinal=ordinal,
                    artifact_metadata={
                        "role": None if role is None else role.value,
                        "path": relative,
                    },
                    # Keep report-level provenance precise.  The complete tool trace
                    # remains available on the task, but a source belongs to an
                    # independent Agent report only when that report cites it.
                    source_ids=_source_ids(content),
                )
            )
        if not complete:
            complete = "\n\n---\n\n".join(item.content_markdown for item in artifacts)
        return tuple(artifacts), complete


def build_tradingagents_engine(settings: Settings) -> TradingAgentsResearchEngine:
    return TradingAgentsResearchEngine(settings)

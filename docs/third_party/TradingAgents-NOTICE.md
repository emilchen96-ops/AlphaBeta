# TradingAgents attribution

AlphaDesk's TA01 worker integrates the public `TradingAgents` Python package as
an explicitly pinned dependency. It does not copy the upstream repository into
the AlphaDesk source tree and does not depend on a developer-machine absolute
path at runtime.

- Upstream: <https://github.com/TauricResearch/TradingAgents>
- Audited revision: `a33fd4c0f134485a43553a2c23a63cb14adbd88f`
- License: Apache License 2.0
- Local audit reference used during development: `D:\QTM\TradingAgents`

The AlphaDesk adapter supplies A-share data and persistence while the upstream
LangGraph, analyst prompts, tool loop, bull/bear debate, trader node and risk
discussion remain the TradingAgents implementation. See the upstream repository
for its copyright and complete license text.

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Signal
from alphadesk_domain.enums import OrderSide, SignalStatus, SignalType
from tests.helpers import require_test_database_url
from tests.integration.test_m05_order_api import _body, _client

pytestmark = [pytest.mark.integration, pytest.mark.r01]


def test_risk_decision_list_detail_filters_limits_and_order_summary() -> None:
    with _client() as (client, account, instrument):
        created = client.post(
            "/api/v1/orders",
            json=_body(str(account.id), str(instrument.id), f"r01-api-pass-{uuid4()}"),
        )
        assert created.status_code == 201
        order = created.json()
        decision_id = order["risk_decision_id"]
        assert decision_id and order["risk_decision"] == "PASS"

        listing = client.get(
            "/api/v1/risk-decisions",
            params={
                "account_id": str(account.id),
                "instrument_id": str(instrument.id),
                "source_type": "MANUAL_ORDER",
                "overall_decision": "ALLOW",
                "order_id": order["id"],
                "has_order": "true",
                "evaluated_from": "2020-01-01T00:00:00Z",
                "evaluated_to": "2100-01-01T00:00:00Z",
                "page": 1,
                "page_size": 1,
            },
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        item = listing.json()["items"][0]
        assert item["id"] == decision_id
        assert item["account"]["id"] == str(account.id)
        assert item["instrument"]["symbol"] == instrument.symbol
        assert item["quantity"] == "1000"

        detail = client.get(f"/api/v1/risk-decisions/{decision_id}")
        assert detail.status_code == 200
        assert [rule["seq"] for rule in detail.json()["rule_results"]] == list(
            range(1, len(detail.json()["rule_results"]) + 1)
        )
        order_detail = client.get(f"/api/v1/orders/{order['id']}").json()
        assert order_detail["risk_decision_id"] == decision_id
        assert order_detail["risk_evaluated_at"]

        limits = client.get("/api/v1/risk-limits/active")
        assert limits.status_code == 200
        payload = limits.json()
        assert payload["configuration_source"] == "服务端权威配置"
        assert "password" not in str(payload).lower()
        assert "alphadesk_risk" not in str(payload).lower()
        assert client.post("/api/v1/risk-limits/active", json={}).status_code == 405
        assert client.patch("/api/v1/risk-limits/active", json={}).status_code == 405


def test_reject_response_has_decision_and_no_order() -> None:
    with _client() as (client, account, instrument):
        before = client.get("/api/v1/orders").json()["total"]
        body = _body(str(account.id), str(instrument.id), f"r01-api-reject-{uuid4()}")
        body["requested_quantity"] = "1000000"
        rejected = client.post("/api/v1/orders", json=body)
        assert rejected.status_code == 422
        error = rejected.json()["error"]
        assert error["code"] == "RISK_ORDER_REJECTED"
        assert error["correlation_id"]
        decision_id = error["details"]["risk_decision_id"]
        decision = client.get(f"/api/v1/risk-decisions/{decision_id}").json()
        assert decision["overall_decision"] == "REJECT"
        assert decision["order_id"] is None
        assert client.get("/api/v1/orders").json()["total"] == before


def test_signal_risk_assessment_never_creates_order() -> None:
    with _client() as (client, account, instrument):
        url = require_test_database_url()

        async def seed_signal() -> Signal:
            engine = create_async_engine(url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            signal = Signal(
                strategy_id=None,
                strategy_version_id=None,
                account_id=None,
                instrument_id=instrument.id,
                signal_type=SignalType.ENTRY,
                side=OrderSide.BUY,
                generated_at=datetime.now(UTC),
                valid_until=datetime.now(UTC) + timedelta(days=1),
                status=SignalStatus.CREATED,
                correlation_id=uuid4(),
                target_quantity=Decimal("100"),
                reference_price=Decimal("10"),
                strategy_key="r01_api_test",
            )
            async with SqlAlchemyUnitOfWork(sessions) as uow:
                await uow.signals.add(signal)
                await uow.commit()
            await engine.dispose()
            return signal

        signal = asyncio.run(seed_signal())
        before = client.get("/api/v1/orders").json()["total"]

        async def boundary_counts() -> tuple[int, int, int, int]:
            engine = create_async_engine(url)
            async with engine.connect() as connection:
                raw = [
                    int((await connection.scalar(text(f"select count(*) from {table}"))) or 0)
                    for table in (
                        "fills",
                        "cash_ledger_entries",
                        "position_ledger_entries",
                        "outbox_messages",
                    )
                ]
            await engine.dispose()
            return raw[0], raw[1], raw[2], raw[3]

        facts_before = asyncio.run(boundary_counts())
        assessed = client.post(
            f"/api/v1/signals/{signal.id}/risk-assessments",
            json={
                "account_id": str(account.id),
                "quantity": None,
                "reference_price": None,
                "idempotency_key": f"signal-risk-{uuid4()}",
            },
        )
        assert assessed.status_code == 200
        assert assessed.json()["source_type"] == "STRATEGY_SIGNAL"
        assert assessed.json()["order_id"] is None
        assert client.get("/api/v1/orders").json()["total"] == before

        assert asyncio.run(boundary_counts()) == facts_before

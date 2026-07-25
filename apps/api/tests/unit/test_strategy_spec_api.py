from fastapi.testclient import TestClient

CORE_TEXT = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线"  # noqa: RUF001


def test_parse_core_strategy_returns_confirmable_spec(client: TestClient) -> None:
    response = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETE"
    assert body["parser_source"] == "LOCAL_RULES"
    assert body["ai_assistance"] == "DISABLED"
    assert body["spec"]["entry"]["conditions"][0]["right"]["exclude_current"] is True
    assert body["spec"]["entry"]["conditions"][1]["right"]["multiplier"] == "1.2"


def test_parse_rejects_code_execution_request(client: TestClient) -> None:
    response = client.post(
        "/api/v1/strategy-specs/parse",
        json={"text": "import os 然后执行Python代码"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STRATEGY_TEXT_UNSAFE"


def test_validate_rejects_unknown_ast_field(client: TestClient) -> None:
    spec = client.post("/api/v1/strategy-specs/parse", json={"text": CORE_TEXT}).json()["spec"]
    spec["entry"]["conditions"][0]["execute"] = "broker.buy()"

    response = client.post("/api/v1/strategy-specs/validate", json={"spec": spec})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STRATEGY_SPEC_UNKNOWN_FIELD"


def test_strategy_templates_expose_safe_core_template(client: TestClient) -> None:
    response = client.get("/api/v1/strategy-templates")

    assert response.status_code == 200
    item = next(row for row in response.json() if row["key"] == "price_volume_breakout_sma_exit")
    assert item["recommended"] is True
    assert item["spec"]["schema_version"] == 1


def test_parse_body_rejects_extra_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/strategy-specs/parse",
        json={"text": CORE_TEXT, "python": "print('x')"},
    )

    assert response.status_code == 422

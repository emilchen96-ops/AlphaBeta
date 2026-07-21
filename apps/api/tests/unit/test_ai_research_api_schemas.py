from uuid import uuid4

import pytest
from pydantic import ValidationError

from alphadesk_api.schemas.ai_research import AIAnalysisCreateBody, AIProviderTestBody


@pytest.mark.unit
@pytest.mark.a01
def test_analysis_request_forbids_secrets_and_trading_fields() -> None:
    base = {
        "analysis_type": "EVENT_SUMMARY",
        "information_item_ids": [uuid4()],
        "idempotency_key": "research-1",
    }
    assert AIAnalysisCreateBody.model_validate(base).analysis_type == "EVENT_SUMMARY"
    for forbidden in ("api_key", "provider_secret", "order", "signal", "trade"):
        with pytest.raises(ValidationError):
            AIAnalysisCreateBody.model_validate({**base, forbidden: "must-not-pass"})


def test_provider_test_request_cannot_override_server_configuration() -> None:
    assert AIProviderTestBody.model_validate({})
    for forbidden in ("base_url", "api_key", "model", "provider"):
        with pytest.raises(ValidationError):
            AIProviderTestBody.model_validate({forbidden: "must-not-pass"})

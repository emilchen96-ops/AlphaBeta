from decimal import Decimal

import pytest

from alphadesk_api.application.risk import ConfiguredRiskLimitsProvider
from alphadesk_api.core.config import Settings

pytestmark = pytest.mark.unit


def test_configured_risk_marker_changes_with_execution_affecting_settings() -> None:
    baseline = ConfiguredRiskLimitsProvider(Settings(environment="test"))
    changed = ConfiguredRiskLimitsProvider(
        Settings(environment="test", risk_max_order_notional=Decimal("123456"))
    )
    repeated = ConfiguredRiskLimitsProvider(Settings(environment="test"))

    assert baseline.version_marker.startswith("r01-config-v2:")
    assert baseline.version_marker == repeated.version_marker
    assert baseline.version_marker != changed.version_marker

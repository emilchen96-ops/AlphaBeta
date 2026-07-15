"""Read-only market-data adapter implementations."""

from alphadesk_api.infrastructure.market_data.csv_file import LocalCsvMarketDataAdapter
from alphadesk_api.infrastructure.market_data.demo import DemoCsvMarketDataAdapter
from alphadesk_api.infrastructure.market_data.disabled import DisabledExternalMarketDataAdapter

__all__ = [
    "DemoCsvMarketDataAdapter",
    "DisabledExternalMarketDataAdapter",
    "LocalCsvMarketDataAdapter",
]

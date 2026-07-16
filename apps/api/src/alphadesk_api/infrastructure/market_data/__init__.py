"""Read-only market-data adapter implementations."""

from alphadesk_api.infrastructure.market_data.akshare_eastmoney import (
    AkShareEastMoneyRealtimeAdapter,
)
from alphadesk_api.infrastructure.market_data.baostock_historical import (
    BaoStockHistoricalMarketDataAdapter,
)
from alphadesk_api.infrastructure.market_data.csv_file import LocalCsvMarketDataAdapter
from alphadesk_api.infrastructure.market_data.demo import DemoCsvMarketDataAdapter
from alphadesk_api.infrastructure.market_data.disabled import DisabledExternalMarketDataAdapter

__all__ = [
    "AkShareEastMoneyRealtimeAdapter",
    "BaoStockHistoricalMarketDataAdapter",
    "DemoCsvMarketDataAdapter",
    "DisabledExternalMarketDataAdapter",
    "LocalCsvMarketDataAdapter",
]

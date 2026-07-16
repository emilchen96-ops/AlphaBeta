"""S01-C strategy catalog and synchronous research-run facade."""

from decimal import Decimal, InvalidOperation
from typing import Any

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.strategy_runner import (
    StrategyRunner,
    StrategyRunRequest,
    StrategyRunResult,
)
from alphadesk_domain.strategy import (
    StrategyError,
    StrategyParameterType,
    StrategyParameterValue,
    StrategyRegistry,
)


def _json_value(value: object) -> object:
    return str(value) if isinstance(value, Decimal) else value


class StrategyCatalogService:
    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def list(self) -> list[dict[str, Any]]:
        return [self._item(item.strategy_key) for item in self._registry.list_metadata()]

    def get(self, strategy_key: str) -> dict[str, Any]:
        try:
            return self._item(strategy_key)
        except StrategyError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc

    def _item(self, strategy_key: str) -> dict[str, Any]:
        metadata = self._registry.get(strategy_key)
        definitions = self._registry.get_parameter_definitions(strategy_key)
        return {
            "strategy_key": metadata.strategy_key,
            "display_name": metadata.display_name,
            "description": metadata.description,
            "version": metadata.version,
            "supported_timeframes": [item.value for item in metadata.supported_timeframes],
            "parameter_schema_version": metadata.parameter_schema_version,
            "parameters": [
                {
                    "name": item.name,
                    "type": item.parameter_type.value,
                    "required": item.required,
                    "default": _json_value(item.default),
                    "description": item.description,
                    "min_value": _json_value(item.min_value),
                    "max_value": _json_value(item.max_value),
                    "choices": list(item.choices or ()),
                }
                for item in definitions
            ],
        }


class StrategyResearchService:
    def __init__(self, uow_factory: UnitOfWorkFactory, registry: StrategyRegistry) -> None:
        self._runner = StrategyRunner(uow_factory, registry)
        self._registry = registry

    def parameters(
        self, strategy_key: str, raw: dict[str, str | int | bool]
    ) -> dict[str, StrategyParameterValue]:
        try:
            definitions = {
                item.name: item for item in self._registry.get_parameter_definitions(strategy_key)
            }
        except StrategyError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        result: dict[str, StrategyParameterValue] = {}
        for name, value in raw.items():
            definition = definitions.get(name)
            if (
                definition is not None
                and definition.parameter_type is StrategyParameterType.DECIMAL
            ):
                if not isinstance(value, str):
                    raise ApplicationError(
                        "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' must be a decimal string"
                    )
                try:
                    result[name] = Decimal(value)
                except InvalidOperation as exc:
                    raise ApplicationError(
                        "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' is invalid"
                    ) from exc
            else:
                result[name] = value
        return result

    async def run(self, request: StrategyRunRequest) -> StrategyRunResult:
        try:
            return await self._runner.run(request)
        except StrategyError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        except ValueError as exc:
            raise ApplicationError(
                "STRATEGY_INVALID_TIME_RANGE", "strategy run request is invalid"
            ) from exc

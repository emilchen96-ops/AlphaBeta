"""Application services for safe strategy building and versioned user strategies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import (
    DeterministicChineseStrategyParser,
    StrategyParseResult,
    StrategySpec,
    StrategySpecCompiler,
    StrategySpecError,
    StrategySpecValidator,
    UserStrategyDefinition,
    UserStrategyVersion,
    strategy_spec_json_schema,
    strategy_spec_preview,
    strategy_spec_to_dict,
)

type UnitOfWorkFactory = Any


def _translate_error(exc: StrategySpecError) -> ApplicationError:
    return ApplicationError(exc.code, str(exc))


def parse_result_to_dict(result: StrategyParseResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "parser_source": result.parser_source,
        "spec": None if result.spec is None else strategy_spec_to_dict(result.spec),
        "preview": list(result.preview),
        "warnings": list(result.warnings),
        "missing_fields": list(result.missing_fields),
        "ai_assistance": "DISABLED",
    }


class StrategySpecService:
    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry
        self._parser = DeterministicChineseStrategyParser()
        self._validator = StrategySpecValidator()
        self._compiler = StrategySpecCompiler()

    def parse(self, text: str) -> dict[str, Any]:
        try:
            return parse_result_to_dict(self._parser.parse(text))
        except StrategySpecError as exc:
            raise _translate_error(exc) from exc

    def validate(self, spec_data: dict[str, Any]) -> dict[str, Any]:
        from alphadesk_domain.strategy_spec import strategy_spec_from_dict

        try:
            spec = self._validator.validate(strategy_spec_from_dict(spec_data))
            return {
                "valid": True,
                "spec": strategy_spec_to_dict(spec),
                "preview": strategy_spec_preview(spec),
                "compiled_strategy_key": self._compiler.register(self._registry, spec),
            }
        except StrategySpecError as exc:
            raise _translate_error(exc) from exc

    def preview(self, spec_data: dict[str, Any]) -> dict[str, Any]:
        from alphadesk_domain.strategy_spec import strategy_spec_from_dict

        try:
            spec = strategy_spec_from_dict(spec_data)
            return {"preview": strategy_spec_preview(spec)}
        except StrategySpecError as exc:
            raise _translate_error(exc) from exc

    @staticmethod
    def schema() -> dict[str, Any]:
        return strategy_spec_json_schema()


def _strategy_dto(
    definition: UserStrategyDefinition, version: UserStrategyVersion
) -> dict[str, Any]:
    return {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "current_version": definition.current_version,
        "archived": definition.archived,
        "spec": strategy_spec_to_dict(version.spec),
        "preview": strategy_spec_preview(version.spec),
        "created_at": definition.created_at,
        "updated_at": definition.updated_at,
    }


class UserStrategyService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def create(self, *, name: str, description: str, spec: StrategySpec) -> dict[str, Any]:
        now = datetime.now(UTC)
        definition = UserStrategyDefinition(
            id=uuid4(),
            name=name.strip() or spec.name,
            description=description.strip() or spec.description,
            created_at=now,
            updated_at=now,
        )
        version = UserStrategyVersion(
            id=uuid4(),
            strategy_id=definition.id,
            version_number=1,
            spec=spec,
            created_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.user_strategies.add_definition(definition)
            await uow.user_strategies.add_version(version)
            await uow.commit()
        return _strategy_dto(definition, version)

    async def get(self, strategy_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definition = await uow.user_strategies.get_definition(strategy_id)
            version = await uow.user_strategies.get_version(strategy_id)
        if definition is None or version is None:
            raise ApplicationError("USER_STRATEGY_NOT_FOUND", "没有找到该策略")
        return _strategy_dto(definition, version)

    async def list(self, *, page: int, page_size: int, include_archived: bool) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definitions, total = await uow.user_strategies.list(
                include_archived=include_archived,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            items: list[dict[str, Any]] = []
            for definition in definitions:
                version = await uow.user_strategies.get_version(definition.id)
                if version is not None:
                    items.append(_strategy_dto(definition, version))
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    async def update(
        self,
        strategy_id: UUID,
        *,
        name: str,
        description: str,
        spec: StrategySpec,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            definition = await uow.user_strategies.get_definition(strategy_id)
            if definition is None:
                raise ApplicationError("USER_STRATEGY_NOT_FOUND", "没有找到该策略")
            if definition.archived:
                raise ApplicationError("USER_STRATEGY_ARCHIVED", "已归档策略不能修改")
            definition.name = name.strip() or spec.name
            definition.description = description.strip() or spec.description
            definition.current_version += 1
            definition.updated_at = now
            version = UserStrategyVersion(
                id=uuid4(),
                strategy_id=strategy_id,
                version_number=definition.current_version,
                spec=spec,
                created_at=now,
            )
            await uow.user_strategies.update_definition(definition)
            await uow.user_strategies.add_version(version)
            await uow.commit()
        return _strategy_dto(definition, version)

    async def archive(self, strategy_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definition = await uow.user_strategies.get_definition(strategy_id)
            version = await uow.user_strategies.get_version(strategy_id)
            if definition is None or version is None:
                raise ApplicationError("USER_STRATEGY_NOT_FOUND", "没有找到该策略")
            definition.archived = True
            definition.updated_at = datetime.now(UTC)
            await uow.user_strategies.update_definition(definition)
            await uow.commit()
        return _strategy_dto(definition, version)

    async def clone(self, strategy_id: UUID) -> dict[str, Any]:
        source = await self.get(strategy_id)
        from alphadesk_domain.strategy_spec import strategy_spec_from_dict

        return await self.create(
            name=f"{source['name']}(副本)",
            description=str(source["description"]),
            spec=strategy_spec_from_dict(source["spec"]),
        )


def default_strategy_templates(registry: StrategyRegistry) -> list[dict[str, Any]]:
    parser = DeterministicChineseStrategyParser()
    core = parser.parse("10日价格突破 + 1.2倍成交量, 5日均线退出, 单只股票、两年日线")
    assert core.spec is not None
    templates: list[dict[str, Any]] = [
        {
            "key": "price_volume_breakout_sma_exit",
            "name": "价格突破与放量",
            "description": "价格突破前期高点且成交量放大, 跌破均线退出。",
            "category": "趋势突破",
            "spec": strategy_spec_to_dict(core.spec),
            "preview": strategy_spec_preview(core.spec),
            "recommended": True,
        }
    ]
    for metadata in registry.list_metadata():
        if metadata.strategy_key == "price_volume_breakout_sma_exit":
            continue
        templates.append(
            {
                "key": metadata.strategy_key,
                "name": metadata.display_name,
                "description": metadata.description,
                "category": "高级内置策略",
                "spec": None,
                "preview": [],
                "recommended": False,
            }
        )
    return templates

"""Safe strategy construction and versioned user-strategy endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.strategy_specs import (
    StrategySpecService,
    UserStrategyService,
    default_strategy_templates,
)
from alphadesk_api.schemas.strategy_specs import (
    StrategyParseResponse,
    StrategyPreviewResponse,
    StrategySpecBody,
    StrategyTemplateResponse,
    StrategyTextParseBody,
    StrategyValidationResponse,
    UserStrategyPageResponse,
    UserStrategyResponse,
    UserStrategyWriteBody,
)
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import StrategySpecError, strategy_spec_from_dict

router = APIRouter(tags=["strategy-builder"])


def _registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def _spec(data: dict[str, Any]):
    try:
        return strategy_spec_from_dict(data)
    except StrategySpecError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc


@router.post("/strategy-specs/parse", response_model=StrategyParseResponse)
async def parse_strategy_spec(
    request: Request, body: StrategyTextParseBody
) -> StrategyParseResponse:
    try:
        result = StrategySpecService(_registry(request)).parse(body.text)
        return StrategyParseResponse.model_validate(result)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/strategy-specs/validate", response_model=StrategyValidationResponse)
async def validate_strategy_spec(
    request: Request, body: StrategySpecBody
) -> StrategyValidationResponse:
    try:
        return StrategyValidationResponse.model_validate(
            StrategySpecService(_registry(request)).validate(body.spec)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/strategy-specs/preview", response_model=StrategyPreviewResponse)
async def preview_strategy_spec(
    request: Request, body: StrategySpecBody
) -> StrategyPreviewResponse:
    try:
        return StrategyPreviewResponse.model_validate(
            StrategySpecService(_registry(request)).preview(body.spec)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/strategy-specs/schema")
async def strategy_spec_schema(request: Request) -> dict[str, Any]:
    return StrategySpecService(_registry(request)).schema()


@router.get("/strategy-templates", response_model=list[StrategyTemplateResponse])
async def list_strategy_templates(request: Request) -> list[StrategyTemplateResponse]:
    return [
        StrategyTemplateResponse.model_validate(item)
        for item in default_strategy_templates(_registry(request))
    ]


@router.get("/strategy-templates/{key}", response_model=StrategyTemplateResponse)
async def strategy_template(request: Request, key: str) -> StrategyTemplateResponse:
    item = next(
        (item for item in default_strategy_templates(_registry(request)) if item["key"] == key),
        None,
    )
    if item is None:
        raise to_app_error(ApplicationError("STRATEGY_TEMPLATE_NOT_FOUND", "没有找到该模板"))
    return StrategyTemplateResponse.model_validate(item)


@router.post(
    "/user-strategies",
    response_model=UserStrategyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_strategy(
    request: Request, body: UserStrategyWriteBody
) -> UserStrategyResponse:
    result = await UserStrategyService(uow_factory(request)).create(
        name=body.name,
        description=body.description,
        spec=_spec(body.spec),
    )
    return UserStrategyResponse.model_validate(result)


@router.get("/user-strategies", response_model=UserStrategyPageResponse)
async def list_user_strategies(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_archived: bool = False,
) -> UserStrategyPageResponse:
    return UserStrategyPageResponse.model_validate(
        await UserStrategyService(uow_factory(request)).list(
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )
    )


@router.get("/user-strategies/{strategy_id}", response_model=UserStrategyResponse)
async def user_strategy(request: Request, strategy_id: UUID) -> UserStrategyResponse:
    try:
        return UserStrategyResponse.model_validate(
            await UserStrategyService(uow_factory(request)).get(strategy_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.put("/user-strategies/{strategy_id}", response_model=UserStrategyResponse)
async def update_user_strategy(
    request: Request, strategy_id: UUID, body: UserStrategyWriteBody
) -> UserStrategyResponse:
    try:
        return UserStrategyResponse.model_validate(
            await UserStrategyService(uow_factory(request)).update(
                strategy_id,
                name=body.name,
                description=body.description,
                spec=_spec(body.spec),
            )
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/user-strategies/{strategy_id}/clone", response_model=UserStrategyResponse)
async def clone_user_strategy(request: Request, strategy_id: UUID) -> UserStrategyResponse:
    try:
        return UserStrategyResponse.model_validate(
            await UserStrategyService(uow_factory(request)).clone(strategy_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/user-strategies/{strategy_id}/archive", response_model=UserStrategyResponse)
async def archive_user_strategy(request: Request, strategy_id: UUID) -> UserStrategyResponse:
    try:
        return UserStrategyResponse.model_validate(
            await UserStrategyService(uow_factory(request)).archive(strategy_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc

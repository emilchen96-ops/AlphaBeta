"""S01-C strategy catalog, synchronous research runs and signal queries."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.strategies import StrategyCatalogService, StrategyResearchService
from alphadesk_api.application.strategy_experiments import (
    ExperimentRunSummary,
    StrategyExperimentQueryService,
    StrategyExperimentRequest,
    StrategyExperimentService,
)
from alphadesk_api.application.strategy_runner import (
    StrategyRunDto,
    StrategyRunQueryService,
    StrategyRunRequest,
    StrategySignalDto,
)
from alphadesk_api.schemas.strategies import (
    StrategyCatalogResponse,
    StrategyExperimentComparisonResponse,
    StrategyExperimentCreateBody,
    StrategyExperimentPageResponse,
    StrategyExperimentResponse,
    StrategyExperimentRunResponse,
    StrategyRunCreateBody,
    StrategyRunDetailResponse,
    StrategyRunPageResponse,
    StrategyRunResponse,
    StrategySignalOverlapResponse,
    StrategySignalPageResponse,
    StrategySignalResponse,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_experiments import StrategyExperiment

router = APIRouter(tags=["strategy-research"])


def registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def run_detail(item: StrategyRunDto) -> StrategyRunDetailResponse:
    warnings = (
        ["NO_MARKET_DATA"] if item.status.value == "COMPLETED" and item.bars_processed == 0 else []
    )
    return StrategyRunDetailResponse(
        run_id=item.id,
        strategy_key=item.strategy_key,
        strategy_version=item.strategy_version,
        status=item.status.value,
        timeframe=item.timeframe.value,
        instrument_ids=list(item.instrument_ids),
        instruments=list(item.instruments),
        parameters=item.parameters,
        start_at=item.start_at,
        end_at=item.end_at,
        bars_processed=item.bars_processed,
        signals_generated=item.signals_generated,
        warnings=warnings,
        started_at=item.started_at,
        completed_at=item.completed_at,
        failed_at=item.failed_at,
        created_at=item.created_at,
        error=None
        if item.error_code is None
        else {"code": item.error_code, "message": item.error_message or "strategy run failed"},
        capabilities={
            "creates_orders": False,
            "uses_risk": False,
            "uses_broker": False,
            "modifies_portfolio": False,
            "is_performance_backtest": False,
        },
    )


def signal_response(item: StrategySignalDto) -> StrategySignalResponse:
    return StrategySignalResponse(
        signal_id=item.id,
        strategy_run_id=item.run_id,
        sequence_number=item.sequence_number,
        strategy_key=item.strategy_key,
        strategy_version=item.strategy_version,
        instrument_id=item.instrument_id,
        instrument={
            "symbol": item.symbol,
            "exchange": item.exchange,
            "name": item.instrument_name,
        },
        signal_type=item.signal_type,
        side=item.side,
        generated_at=item.generated_at,
        bar_timestamp=item.bar_timestamp,
        quantity=item.quantity,
        target_weight=item.target_weight,
        reference_price=item.reference_price,
        confidence=item.confidence,
        reason=item.reason,
        schema_version=item.schema_version,
    )


def experiment_response(
    item: StrategyExperiment, *, replayed: bool = False
) -> StrategyExperimentResponse:
    return StrategyExperimentResponse(
        experiment_id=item.id,
        idempotency_key=item.idempotency_key,
        strategy_key=item.strategy_key,
        strategy_version=item.strategy_version,
        environment=item.environment.value,
        timeframe=item.timeframe.value,
        instrument_ids=list(item.instrument_ids),
        start_at=item.start_at,
        end_at=item.end_at,
        parameter_grid=item.parameter_grid,
        combination_count=item.combination_count,
        runs_completed=item.runs_completed,
        runs_failed=item.runs_failed,
        total_signals=item.total_signals,
        status=item.status.value,
        started_at=item.started_at,
        completed_at=item.completed_at,
        failed_at=item.failed_at,
        error=None
        if item.error_code is None
        else {"code": item.error_code, "message": item.error_message or "experiment failed"},
        correlation_id=item.correlation_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        replayed=replayed,
        capabilities={
            "creates_orders": False,
            "uses_risk": False,
            "uses_broker": False,
            "modifies_portfolio": False,
            "is_performance_backtest": False,
            "is_synchronous": True,
        },
    )


def experiment_run_response(item: ExperimentRunSummary) -> StrategyExperimentRunResponse:
    return StrategyExperimentRunResponse(
        combination_index=item.combination_index,
        normalized_parameters=item.normalized_parameters,
        strategy_run_id=item.strategy_run_id,
        run_status=item.run_status,
        bars_processed=item.bars_processed,
        signals_generated=item.total_signals,
        warning=item.warning,
    )


@router.get("/strategies/catalog", response_model=list[StrategyCatalogResponse])
async def strategy_catalog(request: Request) -> list[StrategyCatalogResponse]:
    return [
        StrategyCatalogResponse.model_validate(item)
        for item in StrategyCatalogService(registry(request)).list()
    ]


@router.get("/strategies/catalog/{strategy_key}", response_model=StrategyCatalogResponse)
async def strategy_catalog_detail(request: Request, strategy_key: str) -> StrategyCatalogResponse:
    try:
        return StrategyCatalogResponse.model_validate(
            StrategyCatalogService(registry(request)).get(strategy_key)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/strategy-runs", response_model=StrategyRunResponse, status_code=status.HTTP_201_CREATED
)
async def create_strategy_run(request: Request, body: StrategyRunCreateBody) -> StrategyRunResponse:
    service = StrategyResearchService(uow_factory(request), registry(request))
    try:
        if (
            body.start_at.tzinfo is None
            or body.end_at.tzinfo is None
            or body.start_at >= body.end_at
        ):
            raise ApplicationError(
                "STRATEGY_INVALID_TIME_RANGE",
                "start_at and end_at must define an aware increasing time range",
            )
        try:
            timeframe = MarketTimeframe(body.timeframe)
        except ValueError as exc:
            raise ApplicationError(
                "STRATEGY_TIMEFRAME_NOT_SUPPORTED", "timeframe is invalid"
            ) from exc
        result = await service.run(
            StrategyRunRequest(
                idempotency_key=body.idempotency_key,
                strategy_key=body.strategy_key,
                timeframe=timeframe,
                start_at=body.start_at,
                end_at=body.end_at,
                instrument_ids=tuple(body.instrument_ids),
                parameters=service.parameters(body.strategy_key, body.parameters),
                correlation_id=request_correlation_id(request),
            )
        )
        return StrategyRunResponse(
            run_id=result.run.id,
            strategy_key=result.run.strategy_key,
            strategy_version=result.run.strategy_version,
            status=result.run.status.value,
            timeframe=result.run.timeframe.value,
            instrument_ids=list(result.run.instrument_ids),
            start_at=result.run.start_at,
            end_at=result.run.end_at,
            bars_processed=result.run.bars_processed,
            signals_generated=result.run.signals_generated,
            warnings=list(result.warnings),
            replayed=result.replayed,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/strategy-runs", response_model=StrategyRunPageResponse)
async def list_strategy_runs(
    request: Request,
    strategy_key: str | None = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    instrument_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> StrategyRunPageResponse:
    items, total = await StrategyRunQueryService(uow_factory(request)).list(
        strategy_key=strategy_key,
        status=run_status,
        instrument_id=instrument_id,
        created_from=created_from,
        created_to=created_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return StrategyRunPageResponse(
        items=[run_detail(item) for item in items], page=page, page_size=page_size, total=total
    )


@router.get("/strategy-runs/{run_id}", response_model=StrategyRunDetailResponse)
async def get_strategy_run(request: Request, run_id: UUID) -> StrategyRunDetailResponse:
    item = await StrategyRunQueryService(uow_factory(request)).get(run_id)
    if item is None:
        raise to_app_error(
            ApplicationError("STRATEGY_RUN_NOT_FOUND", "strategy run does not exist")
        )
    return run_detail(item)


@router.get("/signals", response_model=StrategySignalPageResponse)
async def list_signals(
    request: Request,
    strategy_run_id: UUID | None = None,
    strategy_key: str | None = None,
    instrument_id: UUID | None = None,
    signal_type: str | None = None,
    generated_from: datetime | None = None,
    generated_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> StrategySignalPageResponse:
    items, total = await StrategyRunQueryService(uow_factory(request)).list_all_signals(
        strategy_run_id=strategy_run_id,
        strategy_key=strategy_key,
        instrument_id=instrument_id,
        signal_type=signal_type,
        generated_from=generated_from,
        generated_to=generated_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return StrategySignalPageResponse(
        items=[signal_response(item) for item in items], page=page, page_size=page_size, total=total
    )


@router.get("/strategy-runs/{run_id}/signals", response_model=StrategySignalPageResponse)
async def list_run_signals(
    request: Request,
    run_id: UUID,
    signal_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> StrategySignalPageResponse:
    try:
        items, total = await StrategyRunQueryService(uow_factory(request)).list_signals(
            run_id, (page - 1) * page_size, page_size, signal_type
        )
        return StrategySignalPageResponse(
            items=[signal_response(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/strategy-experiments",
    response_model=StrategyExperimentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_strategy_experiment(
    request: Request, body: StrategyExperimentCreateBody
) -> StrategyExperimentResponse:
    research = StrategyResearchService(uow_factory(request), registry(request))
    settings = request.app.state.settings
    try:
        try:
            timeframe = MarketTimeframe(body.timeframe)
        except ValueError as exc:
            raise ApplicationError(
                "STRATEGY_TIMEFRAME_NOT_SUPPORTED", "timeframe is invalid"
            ) from exc
        result = await StrategyExperimentService(
            uow_factory(request),
            registry(request),
            max_combinations=settings.strategy_experiment_max_combinations,
        ).run(
            StrategyExperimentRequest(
                idempotency_key=body.idempotency_key,
                strategy_key=body.strategy_key,
                parameter_grid=research.parameter_grid(body.strategy_key, body.parameter_grid),
                instrument_ids=tuple(body.instrument_ids),
                timeframe=timeframe,
                start_at=body.start_at,
                end_at=body.end_at,
                correlation_id=request_correlation_id(request),
            )
        )
        return experiment_response(result.experiment, replayed=result.replayed)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/strategy-experiments", response_model=StrategyExperimentPageResponse)
async def list_strategy_experiments(
    request: Request,
    strategy_key: str | None = None,
    experiment_status: Annotated[str | None, Query(alias="status")] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> StrategyExperimentPageResponse:
    items, total = await StrategyExperimentQueryService(uow_factory(request)).list(
        strategy_key=strategy_key,
        status=experiment_status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return StrategyExperimentPageResponse(
        items=[experiment_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/strategy-experiments/{experiment_id}", response_model=StrategyExperimentResponse)
async def get_strategy_experiment(
    request: Request, experiment_id: UUID
) -> StrategyExperimentResponse:
    try:
        item = await StrategyExperimentQueryService(uow_factory(request)).get(experiment_id)
        return experiment_response(item)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/strategy-experiments/{experiment_id}/runs",
    response_model=list[StrategyExperimentRunResponse],
)
async def list_strategy_experiment_runs(
    request: Request, experiment_id: UUID
) -> list[StrategyExperimentRunResponse]:
    try:
        items = await StrategyExperimentQueryService(uow_factory(request)).list_runs(experiment_id)
        return [experiment_run_response(item) for item in items]
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/strategy-experiments/{experiment_id}/comparison",
    response_model=list[StrategyExperimentComparisonResponse],
)
async def get_strategy_experiment_comparison(
    request: Request, experiment_id: UUID
) -> list[StrategyExperimentComparisonResponse]:
    try:
        items = await StrategyExperimentQueryService(uow_factory(request)).comparison(experiment_id)
        return [
            StrategyExperimentComparisonResponse(
                combination_index=item.combination_index,
                normalized_parameters=item.normalized_parameters,
                strategy_run_id=item.strategy_run_id,
                run_status=item.run_status,
                bars_processed=item.bars_processed,
                total_signals=item.total_signals,
                buy_signals=item.buy_signals,
                sell_signals=item.sell_signals,
                first_signal_at=item.first_signal_at,
                last_signal_at=item.last_signal_at,
                signaled_instrument_count=item.signaled_instrument_count,
                warning=item.warning,
            )
            for item in items
        ]
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/strategy-experiments/{experiment_id}/signal-overlap",
    response_model=list[StrategySignalOverlapResponse],
)
async def get_strategy_experiment_signal_overlap(
    request: Request, experiment_id: UUID
) -> list[StrategySignalOverlapResponse]:
    try:
        items = await StrategyExperimentQueryService(uow_factory(request)).signal_overlap(
            experiment_id
        )
        return [
            StrategySignalOverlapResponse(
                left_combination_index=item.left_combination_index,
                right_combination_index=item.right_combination_index,
                intersection_count=item.intersection_count,
                union_count=item.union_count,
                similarity=item.similarity,
            )
            for item in items
        ]
    except ApplicationError as exc:
        raise to_app_error(exc) from exc

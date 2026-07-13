import logging


LOGGER = logging.getLogger("app.main")
LATENCY_BUDGET_MS = 5000.0


def now_ms_since(started_at: float) -> float:
    """Return elapsed milliseconds from the shared application clock."""
    from app import main as main_module

    return (main_module.perf_counter() - started_at) * 1000


def now_counter() -> float:
    """Return the shared application clock for request timing."""
    from app import main as main_module

    return main_module.perf_counter()


def log_verify_complete(
    *,
    started_at: float,
    status_code: int,
    verdict: str | None,
) -> None:
    latency_ms = now_ms_since(started_at)
    LOGGER.info(
        "verify_request_complete",
        extra={
            "latency_ms": latency_ms,
            "over_budget": latency_ms > LATENCY_BUDGET_MS,
            "latency_budget_ms": LATENCY_BUDGET_MS,
            "status_code": status_code,
            "overall_verdict": verdict,
        },
    )


def log_batch_complete(
    *,
    started_at: float,
    status_code: int,
    completed: int,
    failed: int,
) -> None:
    latency_ms = now_ms_since(started_at)
    LOGGER.info(
        "verify_batch_request_complete",
        extra={
            "latency_ms": latency_ms,
            "over_budget": latency_ms > LATENCY_BUDGET_MS,
            "latency_budget_ms": LATENCY_BUDGET_MS,
            "status_code": status_code,
            "item_count": completed + failed,
            "completed_count": completed,
            "failed_count": failed,
        },
    )


def log_batch_stream_complete(
    *,
    started_at: float,
    item_count: int,
    completed: int,
    failed: int,
) -> None:
    latency_ms = now_ms_since(started_at)
    LOGGER.info(
        "verify_batch_stream_request_complete",
        extra={
            "latency_ms": latency_ms,
            "over_budget": latency_ms > LATENCY_BUDGET_MS,
            "latency_budget_ms": LATENCY_BUDGET_MS,
            "status_code": 200,
            "item_count": item_count,
            "completed_count": completed,
            "failed_count": failed,
        },
    )

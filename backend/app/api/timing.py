def now_ms_since(started_at: float) -> float:
    """Return elapsed milliseconds from the shared application clock."""
    from app import main as main_module

    return (main_module.perf_counter() - started_at) * 1000


def now_counter() -> float:
    """Return the shared application clock for request timing."""
    from app import main as main_module

    return main_module.perf_counter()

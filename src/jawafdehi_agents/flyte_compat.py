from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

try:
    import flyte as _flyte
except ImportError:  # pragma: no cover - exercised only without installed deps
    _flyte = None


class _FallbackTaskEnvironment:
    def __init__(self, name: str):
        self.name = name

    def task(
        self, func: Callable[..., Any] | None = None, **_: Any
    ) -> Callable[..., Any]:
        if func is not None:
            return func

        def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
            return inner

        return decorator


def _fallback_trace(
    func: Callable[..., Any] | None = None, **_: Any
) -> Callable[..., Any]:
    if func is not None:
        return func

    def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
        return inner

    return decorator


@contextmanager
def _fallback_group(_: str):
    yield


if _flyte is None:
    flyte = None
    env = _FallbackTaskEnvironment(name="jawafdehi_agents")
    trace = _fallback_trace
    group = _fallback_group
else:
    flyte = _flyte
    env = _flyte.TaskEnvironment(name="jawafdehi_agents")
    trace = _flyte.trace
    group = _flyte.group
